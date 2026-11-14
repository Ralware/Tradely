from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.cache import TTLCache
from app.core.config import get_settings
from app.core.database import Database
from app.services.market import MarketService

settings = get_settings()
if settings.host not in {"127.0.0.1", "localhost", "::1"}:
    raise RuntimeError("Tradely is private by default. HOST must remain localhost/127.0.0.1/::1.")

app = FastAPI(
    title="Tradely API",
    version="0.1.0",
    description="Private, single-user quantitative market analysis. No AI, paper trading or order execution.",
)
app.state.settings = settings
app.state.db = Database(settings.database_file)
app.state.market_service = MarketService(settings)
app.state.response_cache = TTLCache()
app.include_router(router)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets", check_dir=False), name="assets")


@app.get("/", include_in_schema=False)
def home():
    index = FRONTEND_DIST / "index.html"
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "React production build is unavailable. Run the frontend build or use the Vite development server."},
    )
