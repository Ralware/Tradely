from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
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

WEB_DIR = Path(__file__).parent / "web"
app.mount("/assets", StaticFiles(directory=WEB_DIR), name="assets")


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(WEB_DIR / "index.html")
