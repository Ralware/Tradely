"""Browser fixtures run FastAPI on loopback with a disposable SQLite database."""
import os
import socket
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def site(tmp_path_factory):
    if not (ROOT / "frontend/dist/index.html").exists():
        pytest.fail("Build the frontend before running browser tests")
    folder = tmp_path_factory.mktemp("tradely-browser")
    with pytest.MonkeyPatch.context() as patch:
        patch.syspath_prepend(str(ROOT / "backend"))
        for key, value in {
            "DATABASE_PATH": str(folder / "browser.sqlite3"), "BACKUP_ENABLED": "false",
            "BACKUP_GIT_DIR": str(folder / "portable"), "BACKUP_LOCAL_DIR": str(folder / "local"),
            "BACKUP_ON_STARTUP": "false", "BACKUP_ON_SHUTDOWN": "false",
            "TRADINGVIEW_LIVE_SEARCH_ENABLED": "false",
            "TRADINGVIEW_BRIDGE_URL": "http://127.0.0.1:1",
        }.items():
            patch.setenv(key, value)

        from app.main import app
        assert app.state.db.path.resolve() == (folder / "browser.sqlite3").resolve()
        market = app.state.market_service

        def candles(symbol, **kwargs):
            n = 320
            freq = {"1m": "min", "1h": "h", "1wk": "7D", "1mo": "30D"}.get(kwargs.get("interval"), "D")
            index = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("min") - pd.Timedelta(days=1),
                                  periods=n, freq=freq)
            price = 100 + np.arange(n) * 0.1 + np.sin(np.arange(n))
            frame = pd.DataFrame({"open": price, "high": price + 2, "low": price - 2,
                                  "close": price + 1, "volume": 2000.0}, index=index)
            frame.attrs.update(is_adjusted=True, adjustment_status="adjusted", last_bar_confirmed=True)
            return frame, "browser-test-fixture"

        def quotes(symbols):
            return {s: {"lp": 100, "prev_close_price": 95, "lp_time": int(datetime.now(UTC).timestamp()),
                        "delay": 0, "update_mode": "streaming",
                        "currency_code": "INR" if s.startswith(("NSE:", "BSE:")) else "USD"}
                    for s in symbols}, {}

        patch.setattr(market, "candles", candles)
        patch.setattr(market, "quotes", quotes)
        patch.setattr(market, "symbol_info", lambda *args: {})
        patch.setattr(market, "price_metadata", lambda *args, **kwargs: {})
        provider = app.state.news_service.provider
        patch.setattr(provider, "get_symbol_articles", lambda *args: [])
        patch.setattr(provider, "search_instruments", lambda *args: [])
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=3))
            thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 30
                while not server.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        pytest.fail("Disposable backend failed to start")
                    time.sleep(0.05)
                yield f"http://127.0.0.1:{port}"
            finally:
                server.should_exit = True
                thread.join(timeout=12)


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=os.getenv("TRADELY_TEST_BROWSER_CHANNEL") or None)
        yield browser
        browser.close()


@pytest.fixture
def page(browser):
    page = browser.new_page(viewport={"width": 1280, "height": 850}, reduced_motion="reduce")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    page.context.close()
    assert not errors
