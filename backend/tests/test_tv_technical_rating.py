import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tv_technical_rating import (
    MOVING_AVERAGE_KEYS,
    OSCILLATOR_KEYS,
    TechnicalRatingEvaluation,
    build_technical_summary,
    evaluate,
    ohlcv_fingerprint,
    rating_status,
)


def _sample_ohlcv(bars: int = 300) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=bars, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100.0, 300.0, bars), index=index)
    high = close + 2.0
    low = close - 2.0
    open_p = close - 0.5
    volume = pd.Series([10000.0] * bars, index=index)
    return pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=index)


def test_rating_status_thresholds():
    assert rating_status(None) == "-"
    assert rating_status(float("nan")) == "-"
    assert rating_status(0.55) == "Strong Buy"
    assert rating_status(0.2) == "Buy"
    assert rating_status(0.05) == "Neutral"
    assert rating_status(-0.05) == "Neutral"
    assert rating_status(-0.2) == "Sell"
    assert rating_status(-0.55) == "Strong Sell"


def test_evaluation_constituent_count_and_aggregates():
    df = _sample_ohlcv(300)
    ev = evaluate(df)
    assert len(ev.history) == 300
    snap = ev.snapshot()

    assert len(snap["moving_averages"]) == len(MOVING_AVERAGE_KEYS) == 15
    assert len(snap["oscillators"]) == len(OSCILLATOR_KEYS) == 11

    ma_summary = snap["summary"]["moving_averages"]
    osc_summary = snap["summary"]["oscillators"]
    overall = snap["summary"]["overall"]

    assert ma_summary["total"] == 15
    assert osc_summary["total"] == 11
    assert overall["total"] == 26

    assert ma_summary["available"] == 15
    assert osc_summary["available"] == 11
    assert overall["available"] == 26

    # Monotonically increasing close is above all MAs -> all 15 MAs should be Buy (+1) or Neutral for Ichimoku
    assert ma_summary["buy"] >= 14
    assert ma_summary["sell"] == 0
    assert ma_summary["score"] > 0.5
    assert ma_summary["action"] == "Strong Buy"

    assert -1.0 <= osc_summary["score"] <= 1.0
    assert -1.0 <= overall["score"] <= 1.0


def test_ohlcv_fingerprint_changes_on_any_input_mutation():
    df1 = _sample_ohlcv(100)
    fp1 = ohlcv_fingerprint(df1)

    # Identical data produces identical fingerprint
    df2 = df1.copy()
    assert ohlcv_fingerprint(df2) == fp1

    # Mutating close of the last bar changes fingerprint
    df3 = df1.copy()
    df3.iloc[-1, df3.columns.get_loc("close")] += 0.01
    assert ohlcv_fingerprint(df3) != fp1

    # Mutating an older bar must also invalidate derived ratings.
    df_old = df1.copy()
    df_old.iloc[20, df_old.columns.get_loc("low")] -= 0.01
    assert ohlcv_fingerprint(df_old) != fp1

    # Mutating volume changes fingerprint
    df4 = df1.copy()
    df4.iloc[-1, df4.columns.get_loc("volume")] += 1.0
    assert ohlcv_fingerprint(df4) != fp1

    # Appending a bar changes fingerprint
    df5 = pd.concat([df1, df1.iloc[-1:]])
    assert ohlcv_fingerprint(df5) != fp1


def test_technicals_api_with_tv_v3_method(monkeypatch):
    client = TestClient(app, base_url="http://127.0.0.1")
    frame = _sample_ohlcv(300)
    frame.attrs["is_adjusted"] = True

    monkeypatch.setattr(
        app.state.market_service,
        "candles",
        lambda *args, **kwargs: (frame, "tradingview"),
    )

    # 1. Test endpoint with method=v3
    res_v3 = client.get("/api/instruments/TEST/technicals?market=india&interval=1d&method=v3")
    assert res_v3.status_code == 200
    body = res_v3.json()
    assert len(body["moving_averages"]) == 15
    assert len(body["oscillators"]) == 11
    assert body["summary"]["overall"]["total"] == 26
    assert "fingerprint" in body
    assert body["source_name"] == "TradingView TechnicalRating"
    assert "v3" in body["source_version"]

    # 2. Test dedicated technical-ratings endpoint
    res_ratings = client.get("/api/instruments/TEST/technical-ratings?market=india&interval=1d")
    assert res_ratings.status_code == 200
    body_ratings = res_ratings.json()
    assert len(body_ratings["moving_averages"]) == 15
    assert len(body_ratings["oscillators"]) == 11
    assert body_ratings["fingerprint"] == body["fingerprint"]


def test_cache_bypass_flag_passed_to_service(monkeypatch):
    client = TestClient(app, base_url="http://127.0.0.1")
    frame = _sample_ohlcv(300)
    frame.attrs["is_adjusted"] = True

    called_kwargs = {}

    def fake_candles(*args, **kwargs):
        called_kwargs.update(kwargs)
        return frame, "tradingview"

    monkeypatch.setattr(app.state.market_service, "candles", fake_candles)

    client.get("/api/instruments/TEST/technicals?market=india&interval=1d&method=v3&bypass_cache=true")
    assert called_kwargs.get("bypass_cache") is True

    called_kwargs.clear()
    client.get("/api/instruments/TEST/technical-ratings?market=india&interval=1d&refresh=true")
    assert called_kwargs.get("bypass_cache") is True


def test_unavailable_constituents_are_not_counted_as_neutral():
    snapshot = build_technical_summary(_sample_ohlcv(80))
    rows = snapshot["moving_averages"]
    sma_200 = next(row for row in rows if row["key"] == "sma_200")
    summary = snapshot["summary"]["moving_averages"]

    assert sma_200["value"] is None
    assert sma_200["rating"] is None
    assert sma_200["action"] == "Unavailable"
    assert summary["unavailable"] > 0
    assert summary["available"] + summary["unavailable"] == summary["total"]
    assert summary["neutral"] < summary["available"]


def test_multi_component_values_and_parameters_are_exposed():
    snapshot = build_technical_summary(_sample_ohlcv(300))
    rows = {row["key"]: row for row in snapshot["oscillators"] + snapshot["moving_averages"]}

    assert rows["adx_14"]["parameters"] == {"di_length": 14, "adx_smoothing": 14}
    assert {"plus_di_14", "minus_di_14"} <= set(rows["adx_14"]["details"])
    assert {"macd_signal", "macd_hist"} <= set(rows["macd_line"]["details"])
    assert {"stoch_d"} <= set(rows["stoch_k"]["details"])
    assert {"ema_50"} <= set(rows["stoch_rsi_k"]["details"])
    assert {"ichimoku_span1_displaced_26", "ichimoku_span2_displaced_26"} <= set(rows["ichimoku_base"]["details"])
    assert {"bull_power_13", "bear_power_13", "ema_50"} <= set(rows["bbp"]["details"])


def test_analytics_snapshot_is_atomic_and_exposes_provenance(monkeypatch):
    import numpy as np
    import pandas as pd
    import app.api.routes as routes
    from app.main import app
    from app.services.technical_rating_cache import technical_rating_cache

    frame = _sample_ohlcv(300)
    frame.attrs["is_adjusted"] = True
    frame.attrs["last_bar_confirmed"] = True
    monkeypatch.setattr(
        app.state.market_service,
        "candles",
        lambda *args, **kwargs: (frame.copy(), "tradingview"),
    )
    technical_rating_cache.invalidate()
    original = routes.build_tv_technical_summary
    call_count = 0

    def counted(frame_arg):
        nonlocal call_count
        call_count += 1
        return original(frame_arg)

    monkeypatch.setattr(routes, "build_tv_technical_summary", counted)
    client = TestClient(app, base_url="http://127.0.0.1")

    first = client.get(
        "/api/instruments/TEST/analytics-snapshot?market=india&interval=1d&days=3650"
    )
    second = client.get(
        "/api/instruments/TEST/analytics-snapshot?market=india&interval=1d&days=3650"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body["analysis"]["fingerprint"] == body["indicator_series"]["fingerprint"]
    assert body["analysis"]["fingerprint"] == body["technical_ratings"]["fingerprint"]
    assert body["provenance"]["candle_count"] == 300
    assert body["provenance"]["candle_status"] == "confirmed"
    assert body["provenance"]["technical_rating_version"].startswith("v3")
    assert len(body["technical_ratings"]["moving_averages"]) == 15
    assert len(body["technical_ratings"]["oscillators"]) == 11
    assert second.json()["technical_ratings"]["cache_hit"] is True
    assert call_count == 1


def test_analytics_snapshot_refresh_bypasses_market_cache_and_rating_cache(monkeypatch):
    import app.api.routes as routes
    from app.main import app
    from app.services.technical_rating_cache import technical_rating_cache

    frame = _sample_ohlcv(300)
    frame.attrs["is_adjusted"] = True
    calls = []

    def fake_candles(*args, **kwargs):
        calls.append(kwargs.get("bypass_cache", False))
        return frame.copy(), "tradingview"

    monkeypatch.setattr(app.state.market_service, "candles", fake_candles)
    technical_rating_cache.invalidate()
    original = routes.build_tv_technical_summary
    rating_calls = 0

    def counted(frame_arg):
        nonlocal rating_calls
        rating_calls += 1
        return original(frame_arg)

    monkeypatch.setattr(routes, "build_tv_technical_summary", counted)
    client = TestClient(app, base_url="http://127.0.0.1")
    url = "/api/instruments/TEST/analytics-snapshot?market=india&interval=1d&days=3650"
    assert client.get(url).status_code == 200
    assert client.get(url + "&refresh=true").status_code == 200
    assert calls == [False, True]
    assert rating_calls == 2
