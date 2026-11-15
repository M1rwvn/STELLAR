"""Ground Control dashboard for the prototype demo: one static page that uses the public API.

Served by the backend itself (same origin, no CORS, works offline). Marwan's dashboard and Lena's
app use the same endpoints, so this page can be replaced without touching the backend.
"""
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(include_in_schema=False)
PAGE = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"


@router.get("/")
def root():
    return RedirectResponse("/dashboard")


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(PAGE.read_text(encoding="utf-8"))
