from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi.middleware.gzip import GZipMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.api.news_routes import router as news_router
from app.api.backup_routes import router as backup_router
from app.backup.manager import BackupManager
from app.core.config import get_settings
from app.core.database import Database
from app.instruments.resolver import InstrumentResolver
from app.services.database_maintenance import checkpoint, optimize_database
from app.services.market import MarketService
from app.services.quotes import QuoteService
from app.services.analytics_precompute import AnalyticsPrecompute
from app.services.news import NewsService

settings = get_settings()
if settings.host not in {"127.0.0.1", "localhost", "::1"}:
    raise RuntimeError("Tradely is private by default. HOST must remain localhost/127.0.0.1/::1.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The durable queue survives restarts; only one bounded worker is started
    # in this process. Expired leases are recovered when jobs are claimed.
    if settings.analytics_snapshot_retention_enabled:
        try:
            optimize_database(
                app.state.db,
                keep_per_series=settings.analytics_snapshot_retention_per_series,
                vacuum_enabled=settings.maintenance_vacuum_on_startup,
                min_free_bytes=settings.maintenance_vacuum_min_free_bytes,
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "Startup database maintenance failed"
            )
    if settings.backup_on_startup:
        app.state.backup_manager.maybe_backup("startup")
    app.state.analytics_precompute.enqueue_watchlist()
    app.state.analytics_precompute.start()
    app.state.news_service.start()
    try:
        yield
    finally:
        app.state.analytics_precompute.stop()
        app.state.news_service.close()
        if settings.maintenance_checkpoint_on_shutdown:
            try:
                checkpoint(app.state.db)
            except Exception:
                pass
        if settings.backup_on_shutdown:
            app.state.backup_manager.maybe_backup("shutdown")
        app.state.quote_service.shutdown()
        app.state.market_service.tradingview.bridge.close()


app = FastAPI(
    title="Tradely API",
    version="0.1.0",
    description="Private, single-user quantitative market analysis. No AI, paper trading or order execution.",
    lifespan=lifespan,
)
_LOCAL_AUTHORITY = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", re.I)


@app.middleware("http")
async def local_access(request: Request, call_next):
    hosts = request.headers.getlist("host")
    if len(hosts) != 1 or not _LOCAL_AUTHORITY.fullmatch(hosts[0]):
        return JSONResponse({"detail": "Local host required"}, status_code=400)
    origins = request.headers.getlist("origin")
    if origins:
        scheme, _, authority = origins[0].partition("://")
        if len(origins) != 1 or scheme not in {"http", "https"} or not _LOCAL_AUTHORITY.fullmatch(authority):
            return JSONResponse({"detail": "Local browser origin required"}, status_code=403)
    if request.method not in {"GET", "HEAD", "OPTIONS"} and request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "Cross-site mutation refused"}, status_code=403)
    return await call_next(request)


app.add_middleware(GZipMiddleware, minimum_size=4096, compresslevel=3)
app.state.settings = settings
app.state.db = Database(settings.database_file)
app.state.db.backfill_tradingview_metadata()
app.state.market_service = MarketService(settings)
app.state.instrument_resolver = InstrumentResolver(settings, app.state.db, app.state.market_service.tradingview.bridge)
app.state.instrument_resolver.ensure_catalogue()
app.state.quote_service = QuoteService(settings, app.state.market_service, app.state.db)
app.state.analytics_precompute = AnalyticsPrecompute(app.state.db, app.state.market_service)
app.state.news_service = NewsService(app.state.db, app.state.instrument_resolver, settings)
app.state.backup_manager = BackupManager(app.state.db, settings)
app.include_router(router)
app.include_router(news_router)
app.include_router(backup_router)

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


@app.api_route(
    "/api/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def api_not_found(full_path: str):
    return JSONResponse(status_code=404, content={"detail": "Not Found"})


@app.get("/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    """Serve the SPA for client-side routes."""
    index = FRONTEND_DIST / "index.html"
    candidate = (FRONTEND_DIST / full_path).resolve()
    if full_path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
        return FileResponse(candidate)
    if index.is_file():
        return FileResponse(index)
    return JSONResponse(
        status_code=503,
        content={"detail": "React production build is unavailable. Run the frontend build or use the Vite development server."},
    )
