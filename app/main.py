"""
Application entrypoint.

Instantiates the FastAPI app, configures CORS, registers routers, and
exposes a basic health-check endpoint.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import story

app = FastAPI(
    title="Social-to-Story API",
    version="1.0.0",
    description=(
        "A lightweight REST API that converts short social media updates "
        "(X/Twitter post text or URLs) into structured, publication-ready "
        "news narratives — modeled on official government/tech policy "
        "release editorial style — returned as Markdown and JSON."
    ),
)

# Allow all origins for development. Note: browsers disallow combining a
# wildcard origin with allow_credentials=True (the CORS spec forbids it), so
# credentials are left off here. Before deploying to production, replace
# allow_origins=["*"] with an explicit list of trusted origins and enable
# allow_credentials only if the frontend needs cookies/auth headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(story.router)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/health", tags=["health"], summary="Health check")
async def health_check() -> dict:
    """Basic liveness check for uptime monitoring / load balancers."""
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
async def frontend() -> FileResponse:
    """Serve the local frontend when available."""
    return FileResponse(FRONTEND_DIR / "index.html")
