from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_private_no_ai_no_paper_trading():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "private-single-user"
    assert response.json()["ai"] is False
    assert response.json()["paper_trading"] is False
    assert response.json()["order_execution"] is False


def test_risk_endpoint_returns_expected_sizing():
    response = client.post("/api/risk/position-size", json={
        "capital": 100000, "risk_fraction": 0.005, "entry": 1000, "stop": 980
    })
    assert response.status_code == 200
    assert response.json()["quantity"] == 25
    assert response.json()["planned_loss"] == 500


def test_daily_backtest_rejects_intraday_interval():
    response = client.post("/api/backtests/trend-breakout", json={
        "symbol": "RELIANCE", "market": "india", "interval": "15m"
    })
    assert response.status_code == 422


def test_indicator_series_is_additive_and_uses_backend_calculations(monkeypatch):
    import numpy as np
    import pandas as pd

    from app.main import app

    index = pd.date_range("2025-01-01", periods=260, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100.0, 200.0, 260), index=index)
    frame = pd.DataFrame(
        {"open": close, "high": close + 2, "low": close - 2, "close": close, "volume": 1000.0},
        index=index,
    )
    frame.attrs["is_adjusted"] = True

    monkeypatch.setattr(app.state.market_service, "candles", lambda *args, **kwargs: (frame, "test"))

    response = client.get("/api/instruments/TEST/indicators?market=india&limit=120")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 120
    assert body["source"] == "test"
    assert body["is_adjusted"] is True
    assert body["series"][-1]["close"] == 200.0
    assert "sma_200" in body["series"][-1]
    assert "rsi_14" in body["series"][-1]

