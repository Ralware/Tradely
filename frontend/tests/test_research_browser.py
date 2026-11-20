"""Run after the frontend build with Playwright and a Chromium browser installed."""

import csv
import io
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright


def test_browser_search_and_recovery(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = dict(
        os.environ, PYTHONPATH=str(repo / "backend"), DATABASE_PATH=str(tmp_path / "test.sqlite")
    )
    script = (
        "from pathlib import Path; import app.api.research as research; "
        f"research.jobs = Path({str(tmp_path / 'jobs')!r}); "
        f"import uvicorn; uvicorn.run('app.main:app', host='127.0.0.1', port={port})"
    )
    server = subprocess.Popen([sys.executable, "-c", script], cwd=repo, env=environment)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, timeout=1).is_success:
                    break
            except httpx.RequestError:
                pass
            time.sleep(0.2)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel=os.environ.get("PLAYWRIGHT_CHANNEL"), headless=True
            )
            page = browser.new_page()
            page.goto(url + "/backtesting")
            page.get_by_text("Maker 0.05%", exact=False).wait_for()
            page.get_by_label("Configurations", exact=True).fill("4")
            page.get_by_label("Execution mode", exact=True).select_option("gpu")
            page.get_by_role("button", name="Run search").click()
            download = page.get_by_role("link", name="Download all results")
            download.wait_for(timeout=120_000)
            page.reload()
            download.wait_for()
            rows = list(
                csv.DictReader(io.StringIO(httpx.get(url + download.get_attribute("href")).text))
            )
            assert len(rows) == 4
            assert all(r["status"] == "ok" and r["execution_mode"] == "gpu" for r in rows)
            assert all(r["funding_model"] == "HISTORICAL_SETTLEMENTS" for r in rows)
            by_id = {r["config_id"]: r for r in rows}
            config_rows = page.locator("table").filter(has_text="Configuration").locator("tbody tr")
            assert config_rows.count() > 0
            for tr in config_rows.all():
                cells = tr.locator("td").all_inner_texts()
                assert (
                    abs(float(cells[7].replace(",", "")) - float(by_id[cells[0]]["net_pnl"]))
                    <= 0.000051
                )
            page.get_by_label("Configurations", exact=True).fill("20")
            page.get_by_role("button", name="Run search").click()
            page.get_by_role("button", name="Cancel", exact=True).click()
            page.get_by_role("button", name="Resume search").click(timeout=120_000)
            page.get_by_text("20/20 configurations", exact=False).wait_for(timeout=120_000)
            download.wait_for()
            browser.close()
    finally:
        server.terminate()
        server.wait(15)
