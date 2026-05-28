"""FastAPI backend for Healthcare Claim Copilot.

Wraps the existing `scripts/*` modules as HTTP endpoints. The same surface
is consumable from Streamlit (via httpx) or any new React frontend.
Persistence layer extends `src/storage.py` (filesystem JSON) — swap to
SQLite later by replacing `src/api/repositories.py`.
"""
