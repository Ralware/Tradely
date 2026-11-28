"""End-to-end checks against the production bundle and isolated FastAPI process."""
import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import expect


def test_watchlist_keyboard_search_and_refresh(page, site):
    page.goto(site)
    add = page.get_by_role("button", name="Add Instrument")
    add.click()
    dialog = page.get_by_role("dialog")
    search = dialog.get_by_role("combobox")
    expect(search).to_be_focused()
    search.fill("AAPL")
    expect(dialog.get_by_role("option").first).to_contain_text("AAPL")
    search.fill("MSFT")
    search.press("Enter")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("option").first).to_contain_text("MSFT")
    with page.expect_response(lambda r: r.url.endswith("/api/watchlist") and r.request.method == "POST") as saved:
        search.press("Enter")
    assert saved.value.json()["instrument_id"] == "global:NASDAQ:MSFT"
    expect(add).to_be_focused()
    expect(page.get_by_role("row", name="Open analysis for MSFT")).to_contain_text("100")
    with page.expect_response(lambda r: "/api/watchlist" in r.url and r.request.method == "GET"):
        page.get_by_role("button", name="Refresh watchlist data").click()
    page.get_by_role("button", name="Actions for MSFT").click()
    page.get_by_role("menuitem", name="Remove").click()
    expect(page.get_by_role("row", name="Open analysis for MSFT")).to_have_count(0)


def test_obsolete_resolution_and_failed_retry(page, site):
    page.goto(site)
    search = page.get_by_role("combobox", name="Instrument Search").first
    requests = []
    page.route(re.compile(r"/api/instruments/global(%3A|:)NASDAQ(%3A|:)AAPL$", re.I), requests.append)
    search.fill("AAPL")
    expect(page.get_by_role("option").first).to_contain_text("AAPL")
    with page.expect_request(lambda r: unquote(r.url).endswith("/global:NASDAQ:AAPL")):
        search.press("Enter")
    search.press("Enter")
    assert len(requests) == 1
    search.fill("MSFT")
    requests[0].fulfill(json={"detail": "Fixture resolution failure"}, status=503)
    expect(page.get_by_role("option").first).to_contain_text("MSFT")
    assert page.url == site + "/"
    search.fill("AAPL")
    expect(page.get_by_role("option").first).to_contain_text("AAPL")
    with page.expect_request(lambda r: unquote(r.url).endswith("/global:NASDAQ:AAPL")):
        search.press("Enter")
    requests[-1].fulfill(json={"detail": "Fixture resolution failure"}, status=503)
    expect(page.get_by_role("alert")).to_contain_text("Fixture resolution failure")
    page.unroute_all()
    search.press("Enter")
    page.wait_for_url("**/analysis?**")
    assert "instrument=global:NASDAQ:AAPL" in unquote(page.url)


@pytest.mark.parametrize("width", [320, 375, 390, 768, 1024, 1280, 1440, 1920])
def test_route_layouts(page, site, width):
    page.set_viewport_size({"width": width, "height": 800})
    page.goto(site)
    for label in ("Watchlist", "Analytics", "Portfolio", "Backtesting", "News"):
        link = page.get_by_role("navigation").get_by_role("link", name=label, exact=True)
        expect(link).to_be_in_viewport(ratio=1)
        link.click()
        expect(link).to_have_attribute("aria-current", "page")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
