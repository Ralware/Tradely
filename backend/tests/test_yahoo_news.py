from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.core.database import Database
from app.providers.yahoo_news import (
    YahooFinanceNewsProvider,
    canonical_article_url,
    normalize_search_article,
    safe_http_url,
)


def test_search_article_normalizes_fields_and_keeps_utc_and_safe_links():
    raw = {
        "uuid": "article-1",
        "title": "<b>Apple</b> launches a new service",
        "publisher": "Example Publisher",
        "link": "https://publisher.example/story?utm_source=yahoo&ref=feed#section",
        "providerPublishTime": 1_700_000_000,
        "summary": "<p>Details&nbsp;here</p>",
        "thumbnail": {"resolutions": [{"url": "javascript:alert(1)"}]},
        "relatedTickers": ["AAPL", "MSFT", "AAPL"],
    }
    article = normalize_search_article(raw)
    assert article is not None
    assert article["title"] == "Apple launches a new service"
    assert article["summary"] == "Details here"
    assert article["related_symbols"] == ["AAPL", "MSFT"]
    assert article["published_at"].endswith("+00:00")
    assert article["thumbnail_url"] is None
    assert article["canonical_url"] == "https://publisher.example/story?ref=feed"


def test_url_safety_and_canonical_tracking_cleanup():
    assert safe_http_url("javascript:alert(1)") is None
    assert safe_http_url("https://user:secret@example.com/news") is None
    assert canonical_article_url("https://EXAMPLE.com/story/?utm_campaign=x&keep=1#part") == "https://example.com/story?keep=1"


def test_provider_filters_exact_related_ticker_and_deduplicates():
    payload = {
        "news": [
            {
                "uuid": "a1", "title": "Apple reports results", "publisher": "Wire",
                "link": "https://example.com/a?utm_source=yahoo", "providerPublishTime": 1_700_000_000,
                "relatedTickers": ["AAPL"],
            },
            {
                "uuid": "b1", "title": "Apple story not this issuer", "publisher": "Wire",
                "link": "https://example.com/b", "providerPublishTime": 1_700_000_010,
                "relatedTickers": ["APLE"],
            },
            {
                "uuid": "a2", "title": "Duplicate Apple results", "publisher": "Wire",
                "link": "https://example.com/a", "providerPublishTime": 1_700_000_001,
                "relatedTickers": ["AAPL"],
            },
        ]
    }

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(respond))
    provider = YahooFinanceNewsProvider(client=client, max_retries=0)
    try:
        articles = provider.get_symbol_articles("AAPL", "Apple Inc.")
    finally:
        provider.close()
    assert len(articles) == 1
    assert articles[0]["title"] == "Apple reports results"


def test_provider_falls_back_to_conservative_rss_and_leaves_missing_fields_null():
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "finance/search" in request.url.path:
            return httpx.Response(200, json={"news": []}, request=request)
        return httpx.Response(
            200,
            text="""<?xml version=\"1.0\"?><rss version=\"2.0\"><channel>
            <item><guid>rss-1</guid><title>Apple announces results</title><link>https://publisher.example/apple</link>
            <description>Apple said revenue rose.</description><pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate></item>
            <item><guid>rss-2</guid><title>Markets rally broadly</title><link>https://publisher.example/market</link>
            <description>Investors react to rates.</description><pubDate>Tue, 14 Nov 2023 22:13:20 GMT</pubDate></item>
            </channel></rss>""",
            request=request,
        )

    provider = YahooFinanceNewsProvider(client=httpx.Client(transport=httpx.MockTransport(respond)), max_retries=0)
    try:
        articles = provider.get_symbol_articles("AAPL", "Apple Inc.")
    finally:
        provider.close()
    assert len(requests) == 2
    assert len(articles) == 1
    assert articles[0]["publisher"] is None
    assert articles[0]["thumbnail_url"] is None
    assert articles[0]["published_at"] == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC).isoformat()


def test_news_cache_persistence_date_and_text_filters(tmp_path: Path):
    db = Database(tmp_path / "news-test.sqlite3")
    article = {
        "yahoo_id": "persist-1", "title": "Apple quarterly earnings", "summary": "Revenue grew",
        "publisher": "Newswire", "published_at": "2024-01-02T12:00:00+00:00",
        "article_url": "https://publisher.example/story", "canonical_url": "https://publisher.example/story",
        "thumbnail_url": None, "related_symbols": ["AAPL"], "source": "Yahoo Finance Search",
    }
    db.save_news_refresh(
        instrument_id="global:NASDAQ:AAPL", symbol="AAPL", articles=[article],
        attempted_at="2024-01-02T13:00:00+00:00", expires_at="2024-01-02T13:05:00+00:00",
    )
    rows = db.list_news(instrument_id="global:NASDAQ:AAPL", query="earnings", date_from="2024-01-02T00:00:00+00:00")
    assert len(rows) == 1
    assert rows[0]["related_symbols"] == ["AAPL"]
    assert rows[0]["article_id"]
    assert db.count_news(instrument_id="global:NASDAQ:AAPL", query="earnings") == 1
    assert db.count_news(instrument_id="global:NASDAQ:AAPL", query="Apple", date_to="2024-01-01T00:00:00+00:00") == 0
    assert db.news_cache_state("global:NASDAQ:AAPL")["status"] == "ok"


def test_news_date_filter_is_inclusive_timezone_aware_and_skips_invalid_timestamps(tmp_path: Path):
    db = Database(tmp_path / "news-range-test.sqlite3")
    timestamps = [
        ("before", "2026-10-22T18:29:59+00:00"),
        ("start", "2026-10-23T00:00:00+05:30"),
        ("end", "2026-11-23T23:59:59+05:30"),
        ("after", "2026-11-24T00:00:00+05:30"),
        ("invalid", "not-a-timestamp"),
        ("missing", None),
    ]
    articles = [{
        "yahoo_id": identity, "title": identity, "summary": None, "publisher": "Wire",
        "published_at": published_at, "article_url": f"https://news.example/{identity}",
        "canonical_url": f"https://news.example/{identity}", "thumbnail_url": None,
        "related_symbols": ["AAPL"], "source": "Yahoo Finance Search",
    } for identity, published_at in timestamps]
    db.save_news_refresh(
        instrument_id="global:NASDAQ:AAPL", symbol="AAPL", articles=articles,
        attempted_at="2026-11-24T00:00:00+00:00", expires_at="2026-11-24T00:05:00+00:00",
    )

    start_utc = "2026-10-22T18:30:00+00:00"
    end_utc = "2026-11-23T18:29:59.999999+00:00"
    rows = db.list_news(instrument_id="global:NASDAQ:AAPL", date_from=start_utc, date_to=end_utc)

    assert [row["title"] for row in rows] == ["end", "start"]
    assert db.count_news(instrument_id="global:NASDAQ:AAPL", date_from=start_utc, date_to=end_utc) == 2


def test_news_date_filter_compares_exact_microseconds_and_list_matches_count(tmp_path: Path):
    db = Database(tmp_path / "news-microseconds.sqlite3")
    timestamps = [
        ("one-microsecond-before", "2026-11-01T12:00:00.123455+00:00"),
        ("lower-bound", "2026-11-01T12:00:00.123456+00:00"),
        ("upper-bound", "2026-11-01T12:00:00.123457+00:00"),
        ("one-microsecond-after", "2026-11-01T12:00:00.123458+00:00"),
    ]
    articles = [{
        "yahoo_id": name, "title": name, "published_at": published,
        "article_url": f"https://news.example/{name}",
        "canonical_url": f"https://news.example/{name}", "related_symbols": ["AAPL"],
        "source": "Yahoo Finance Search",
    } for name, published in timestamps]
    db.save_news_refresh(
        instrument_id="global:NASDAQ:AAPL", symbol="AAPL", articles=articles,
        attempted_at="2026-11-02T00:00:00+00:00", expires_at="2026-11-02T00:05:00+00:00",
    )

    rows = db.list_news(
        instrument_id="global:NASDAQ:AAPL",
        date_from="2026-11-01T17:30:00.123456+05:30",
        date_to="2026-11-01T12:00:00.123457Z",
    )
    assert {row["title"] for row in rows} == {"lower-bound", "upper-bound"}
    assert len(rows) == db.count_news(
        instrument_id="global:NASDAQ:AAPL",
        date_from="2026-11-01T17:30:00.123456+05:30",
        date_to="2026-11-01T12:00:00.123457Z",
    ) == 2


def test_schema_v5_news_timestamps_are_additively_backfilled(tmp_path: Path):
    path = tmp_path / "legacy-news.sqlite3"
    db = Database(path)
    article = {
        "yahoo_id": "legacy-1", "title": "Legacy timestamp",
        "published_at": "2025-05-06T07:08:09.123456+05:30",
        "article_url": "https://news.example/legacy", "related_symbols": ["AAPL"],
        "source": "Yahoo Finance Search",
    }
    db.save_news_refresh(
        instrument_id="global:NASDAQ:AAPL", symbol="AAPL", articles=[article],
        attempted_at="2025-05-06T00:00:00+00:00", expires_at="2025-05-06T00:05:00+00:00",
    )
    with db.connect() as connection:
        connection.execute("DROP INDEX idx_news_published_us")
        connection.execute("ALTER TABLE news_articles DROP COLUMN published_at_us")
        connection.execute("PRAGMA user_version = 5")

    migrated = Database(path)
    with migrated.connect() as connection:
        row = connection.execute("SELECT published_at,published_at_us FROM news_articles").fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert row["published_at"] == "2025-05-06T01:38:09.123456+00:00"
    assert row["published_at_us"] is not None
    assert version >= 6
    assert migrated.count_news(
        instrument_id="global:NASDAQ:AAPL",
        date_from="2025-05-06T07:08:09.123456+05:30",
        date_to="2025-05-06T07:08:09.123456+05:30",
    ) == 1
