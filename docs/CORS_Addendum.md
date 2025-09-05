# CORS Addendum (for separate UI host)
If your UI is served from a different origin (e.g., GitHub Pages), add that origin to `allow_origins` in `app/main.py`.

Example:
```python
origins = [
    "http://127.0.0.1:8000", "http://localhost:8000",
    "https://creativityquarks.github.io"
]
```
