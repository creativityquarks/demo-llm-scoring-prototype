import os
import re
import json
from typing import Dict, Any, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# For "Option B — Serve the GUI from FastAPI (same origin; no CORS)"
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from dotenv import load_dotenv
load_dotenv()  # load .env if present

# --- Config ---
USE_MOCK = os.getenv("USE_MOCK", "0") == "1"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- FastAPI ---
app = FastAPI(title="Landing Page Scoring Prototype API - Demo", version="0.1.0")

# For "Option B — Serve the GUI from FastAPI (same origin; no CORS)"
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")

# CORS (allow local dev & GitHub Pages)
origins = [
    "http://127.0.0.1:8000", "http://localhost:8000",
    "http://127.0.0.1:8001", "http://localhost:8001",
    "http://127.0.0.1:5500", "http://localhost:5500",
    # Add your GitHub Pages origin if you host the UI there:
    # "https://<your-user>.github.io"
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Models ---
class ScoreRequest(BaseModel):
    html: str = Field(..., description="Raw HTML of the page")
    url: Optional[str] = Field(None, description="Optional URL (for context)")
    criteria: Optional[List[str]] = Field(None, description="List of criteria to evaluate")

class ScoreResponse(BaseModel):
    scores: Dict[str, Dict[str, Any]]
    overall: float
    notes: str

class CompareRequest(BaseModel):
    before_html: str
    after_html: str
    url: Optional[str] = None
    criteria: Optional[List[str]] = None

class CompareResponse(BaseModel):
    before: ScoreResponse
    after: ScoreResponse
    delta: Dict[str, float]

# --- Logic ---
DEFAULT_CRITERIA = ["clarity", "credibility", "cta"]

def _mock_score(html: str, criteria: List[str]) -> Dict[str, Any]:
    txt = re.sub(r"<[^>]+>", " ", html or "").lower()
    have_h1   = bool(re.search(r"<h1[^>]*>.*?</h1>", html or "", flags=re.I|re.S))
    have_title= bool(re.search(r"<title[^>]*>.*?</title>", html or "", flags=re.I|re.S))
    have_btn  = ("<button" in (html or "").lower()) or any(k in txt for k in ["get started","start free","sign up","contact","try free"])
    trust_kw  = sum(k in txt for k in ["trusted by","testimonials","review","reviews","privacy","secure","https","iso","gdpr","clients","partners"])
    words     = len(txt.split())

    scores: Dict[str, Dict[str, Any]] = {}

    if "clarity" in criteria:
        s = 4 + (3 if have_h1 else 0) + (2 if have_title else 0) + (1 if 50 <= words <= 400 else 0)
        s = max(1, min(10, s))
        scores["clarity"] = {"score": s, "feedback": ("Clear headline." if have_h1 else "Add a clear H1.") + (" Keep copy concise." if words>400 else "")}

    if "credibility" in criteria:
        s = 3 + min(7, trust_kw)
        s = max(1, min(10, s))
        fb_parts = []
        if trust_kw == 0: fb_parts.append("Add testimonials/trust badges.")
        if "https" not in txt: fb_parts.append("Show security/privacy info.")
        scores["credibility"] = {"score": s, "feedback": " ".join(fb_parts) or "Good trust signals."}

    if "cta" in criteria:
        s = 4 + (4 if have_btn else 0) + (2 if have_h1 else 0)
        s = max(1, min(10, s))
        scores["cta"] = {"score": s, "feedback": ("CTA visible." if have_btn else "Add a prominent CTA.")}

    for c in criteria:
        scores.setdefault(c, {"score": 5, "feedback": "OK"})

    overall = round(sum(v["score"] for v in scores.values())/len(scores), 2)
    return {"scores": scores, "overall": overall, "notes": "Mock mode: heuristic scoring"}

def _build_messages(html: str, url: Optional[str], criteria: List[str]) -> list:
    SYSTEM_PROMPT = (
        "You are an assistant that evaluates marketing landing pages.\n"
        "Score each requested criterion from 1 to 10 and give concise, actionable feedback (max ~25 words each).\n"
        "Be consistent and fair across pages. When content is missing, explain briefly.\n"
        "Return ONLY valid JSON. Use integers for scores."
    )
    crit_list = "\n".join(f"- {c}" for c in criteria)
    user_prompt = f"""Evaluate the landing page below.
URL: {url or "N/A"}

Criteria:
{crit_list}

Return a JSON object with:
{{
  "scores": {{
    "<criterion>": {{ "score": <int 1-10>, "feedback": "<string>" }}
  }},
  "overall": <float>,
  "notes": "<short rationale>"
}}

Page HTML (truncated OK):
<<<HTML_START>>>
{html}
<<<HTML_END>>>"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

def llm_score_page(html: str, url: Optional[str], criteria: Optional[List[str]] = None, model: str = "gpt-5-mini") -> Dict[str, Any]:
    criteria = criteria or DEFAULT_CRITERIA

    # Mock if desired or no key
    if USE_MOCK or not OPENAI_API_KEY:
        return _mock_score(html, criteria)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)

        messages = _build_messages(html, url, criteria)
        resp = client.chat.completions.create(
            model=model, temperature=0.2, messages=messages,
            response_format={"type": "json_object"}
        )
        content = resp.choices[0].message.content
        data = json.loads(content)

        data.setdefault("scores", {})
        for c in criteria:
            data["scores"].setdefault(c, {"score": 0, "feedback": ""})
        if "overall" not in data or not isinstance(data["overall"], (int, float)):
            vals = [v["score"] for v in data["scores"].values()]
            data["overall"] = round(sum(vals)/len(vals), 2) if vals else 0.0
        data.setdefault("notes", "")
        return data

    except Exception as e:
        # Graceful fallback
        mock = _mock_score(html, criteria)
        mock["notes"] = f"Mock fallback due to error: {e.__class__.__name__}"
        return mock

# --- Routes ---
@app.get("/healthz")
def healthz():
    return {"status": "ok", "mock": USE_MOCK}

@app.post("/score", response_model=ScoreResponse)
def score_page(req: ScoreRequest):
    result = llm_score_page(req.html, req.url, req.criteria)
    return result

@app.post("/compare", response_model=CompareResponse)
def compare_pages(req: CompareRequest):
    criteria = req.criteria or DEFAULT_CRITERIA
    before = llm_score_page(req.before_html, req.url, criteria)
    after = llm_score_page(req.after_html, req.url, criteria)
    delta: Dict[str, float] = {}
    for c in criteria + ["overall"]:
        b = before["scores"][c]["score"] if c in before["scores"] else before["overall"]
        a = after["scores"][c]["score"] if c in after["scores"] else after["overall"]
        delta[c] = round((a - b), 2)
    return {"before": before, "after": after, "delta": delta}
