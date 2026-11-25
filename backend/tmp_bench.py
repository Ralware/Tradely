from __future__ import annotations

import gzip
import json
import sqlite3
import time

import pandas as pd

from app.services.analytics_precompute import _decode, _records
from app.services.indicators import compute_indicators
from app.services.strategy import evaluate_trend_breakout
from app.services.tv_technical_rating import build_technical_summary

DB = r"C:\Users\Ral\OneDrive - PESUNIVERSITY\Documents\PlayGround\Tradely\data\tradely.sqlite3"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT payload,payload_checksum FROM market_analytics_snapshots "
    "WHERE instrument_id=? AND interval=? AND status='READY' ORDER BY generated_at DESC LIMIT 1",
    ("crypto:BINANCE:ALGOUSDT", "1m"),
).fetchone()
print("snapshot bytes:", len(row["payload"]))
t0 = time.perf_counter()
payload = _decode(row["payload"], row["payload_checksum"])
print(f"decode: {time.perf_counter()-t0:.3f}s rows={len(payload['analysis']['candles'])}")

candles = payload["analysis"]["candles"]
frame = pd.DataFrame(candles)
frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
frame = frame.set_index("timestamp")[["open", "high", "low", "close", "volume"]]
frame.attrs.update({"source": payload["source"], "is_adjusted": payload["is_adjusted"]})
print("frame", frame.shape)

t0 = time.perf_counter(); ind = compute_indicators(frame); print(f"compute_indicators: {time.perf_counter()-t0:.3f}s")
t0 = time.perf_counter(); tech = build_technical_summary(frame); print(f"technical_summary: {time.perf_counter()-t0:.3f}s")
t0 = time.perf_counter()
for direction in ("long_only", "short_only", "long_short"):
    for position in (None, "LONG", "SHORT"):
        evaluate_trend_breakout(frame, symbol="ALGOUSDT", market="crypto", source="tradingview",
                                direction_mode=direction, position_side=position, indicators=ind)
print(f"9 strategy evals: {time.perf_counter()-t0:.3f}s")
t0 = time.perf_counter(); rec_c = _records(frame); print(f"records(candles): {time.perf_counter()-t0:.3f}s")
t0 = time.perf_counter(); rec_i = _records(ind); print(f"records(indicators): {time.perf_counter()-t0:.3f}s")
print("candles json MB", len(json.dumps(rec_c, default=str)) / 1e6)
print("series json MB", len(json.dumps(rec_i, default=str)) / 1e6)
t0 = time.perf_counter(); raw = json.dumps(payload, separators=(",", ":"), default=str).encode(); print(f"json encode payload: {time.perf_counter()-t0:.3f}s MB={len(raw)/1e6:.1f}")
t0 = time.perf_counter(); gz = gzip.compress(raw, compresslevel=6); print(f"gzip: {time.perf_counter()-t0:.3f}s MB={len(gz)/1e6:.1f}")

t0 = time.perf_counter()
with sqlite3.connect(DB) as c:
    c.execute("BEGIN IMMEDIATE")
    rows = [("crypto:BINANCE:ALGOUSDT", "1m", pd.Timestamp(ts).isoformat(), float(r.open), float(r.high),
             float(r.low), float(r.close), float(r.volume), "tradingview", "adjusted", "now") for ts, r in frame.iterrows()]
    c.executemany(
        """INSERT INTO market_bars VALUES(?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(instrument_id,interval,timestamp,adjustment_status,source) DO UPDATE SET
           open=excluded.open,high=excluded.high,low=excluded.low,close=excluded.close,
           volume=excluded.volume,updated_at=excluded.updated_at""", rows)
    c.commit()
print(f"sqlite 10k upsert: {time.perf_counter()-t0:.3f}s")
