"""Static asset helpers for the WebUI client.

Serves favicon, robots.txt, and other tiny static files inline
so the dashboard remains self-contained.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter()


FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="45" fill="#58a6ff"/>'
    '<text x="50" y="65" font-size="45" text-anchor="middle" fill="#0d1117">E</text>'
    "</svg>"
)

ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


@router.get("/favicon.svg")
async def favicon() -> PlainTextResponse:
    return PlainTextResponse(FAVICON_SVG, media_type="image/svg+xml")


@router.get("/robots.txt")
async def robots_txt() -> PlainTextResponse:
    return PlainTextResponse(ROBOTS_TXT, media_type="text/plain")


def static_routes() -> APIRouter:
    """Return the static asset router."""
    return router
