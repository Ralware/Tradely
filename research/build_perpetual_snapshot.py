"""Build a USD-M research snapshot from Binance public history."""

import argparse
import hashlib
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import httpx
import pandas as pd

DEST = Path(__file__).parent / "data" / "BTCUSDT_USDM"
START, END = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")


HISTORY_START = pd.Timestamp("2020-01-01", tz="UTC")


def month_data(month, symbol="BTCUSDT"):
    name = f"{symbol}-2h-{month:%Y-%m}.zip"
    url = f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/2h/{name}"
    archive = httpx.get(url, timeout=60).raise_for_status().content
    expected = httpx.get(url + ".CHECKSUM", timeout=60).raise_for_status().text.split()[0]
    if hashlib.sha256(archive).hexdigest() != expected:
        raise ValueError(f"Archive checksum mismatch for {name}")
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        with z.open(name.replace(".zip", ".csv")) as f:
            df = pd.read_csv(
                f,
                header=None,
                usecols=range(6),
                names=["timestamp", "open", "high", "low", "close", "volume"],
            )
    df = df.loc[pd.to_numeric(df.timestamp, errors="coerce").notna()].astype(float)
    df.index = pd.to_datetime(df.pop("timestamp"), unit="ms", utc=True)
    return df, {"url": url, "sha256": expected}


def funding_history(symbol, start, end):
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    cursor, end_ms = start.value // 10**6, end.value // 10**6
    events = []
    while cursor < end_ms:
        page = (
            httpx.get(
                url,
                params=dict(symbol=symbol, startTime=cursor, endTime=end_ms - 1, limit=1000),
                timeout=60,
            )
            .raise_for_status()
            .json()
        )
        if not page:
            break
        events.extend(page)
        cursor = page[-1]["fundingTime"] + 1
    stamps = pd.to_datetime([e["fundingTime"] for e in events], unit="ms", utc=True)
    expected_events = pd.date_range(start, end, freq="8h", inclusive="left")
    if not stamps.floor("h").equals(expected_events):
        raise ValueError("Unexpected funding history coverage")
    return url, events, stamps


def build(
    symbol="BTCUSDT",
    dest=DEST,
    history_start=HISTORY_START,
    start=START,
    end=END,
    *,
    include_funding=True,
):
    if re.fullmatch(r"[A-Z0-9]+USDT", symbol) is None:
        raise ValueError("Expected a USDT contract symbol")
    if not history_start <= start < end or any(
        date != date.normalize() or date.day != 1 for date in (history_start, start, end)
    ):
        raise ValueError("Use ordered UTC month starts for history, trading, and cutoff")

    with ThreadPoolExecutor(4) as pool:
        parts = list(
            pool.map(
                partial(month_data, symbol=symbol),
                pd.date_range(history_start, end, freq="MS", inclusive="left"),
            )
        )
    bars = pd.concat([data for data, _ in parts])
    expected = pd.date_range(history_start, end, freq="2h", inclusive="left")
    if not bars.index.equals(expected):
        raise ValueError("Incomplete or unordered candle history")
    url, events, stamps = funding_history(symbol, start, end) if include_funding else (None, [], [])
    dest.mkdir(parents=True, exist_ok=True)
    for interval, name in [("2h", "2hours"), ("4h", "4hours"), ("1D", "1day"), ("7D", "1week")]:
        res = bars.resample(interval, origin=pd.Timestamp("1970-01-05", tz="UTC"))
        frame = res.agg(dict(open="first", high="max", low="min", close="last", volume="sum"))
        frame = frame[res.size() == pd.Timedelta(interval).value // pd.Timedelta("2h").value].copy()
        # Binance's scheduled settlement is on the hour. Retain the exchange
        # publication time in the provenance file. Record USD paid per long unit.
        if include_funding:
            opened = dict.fromkeys(frame.index, 0.0)
            inside = opened.copy()
            for t, e in zip(stamps.floor("h"), events):
                i = frame.index.searchsorted(t, side="right") - 1
                if i >= 0 and t < frame.index[i] + pd.Timedelta(interval):
                    payment = float(e["fundingRate"]) * float(e["markPrice"])
                    (opened if t == frame.index[i] else inside)[frame.index[i]] += payment
            frame["funding_open_per_unit"] = opened.values()
            frame["funding_inside_per_unit"] = inside.values()
        frame["warmup_only"] = (frame.index < start).astype(int)
        frame.insert(0, "timestamp", frame.index.as_unit("ms").asi8)
        frame.to_csv(dest / f"{symbol}_{name}.csv", index=False)
    (dest / "sources.json").write_text(
        json.dumps(
            dict(
                warmup_start=str(history_start),
                start=str(start),
                cutoff=str(end),
                symbol=symbol,
                market="Binance USD-M perpetual",
                archives=[record for _, record in parts],
                funding_endpoint=url,
                funding_model="HISTORICAL_SETTLEMENTS"
                if include_funding
                else "UNAVAILABLE_EXCLUDED_ZERO",
                funding_events=events,
            ),
            separators=(",", ":"),
        ),
        encoding="utf8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--history-start", default="2020-01-01")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-01-01")
    parser.add_argument(
        "--exclude-funding",
        action="store_true",
        help="Use only candles if historical settlements are unavailable",
    )
    args = parser.parse_args()
    if (args.symbol != "BTCUSDT" or args.exclude_funding) and args.output is None:
        parser.error("--output is required for a custom symbol or a snapshot without funding")
    dates = [
        pd.to_datetime(value, utc=True) for value in (args.history_start, args.start, args.end)
    ]
    build(args.symbol, args.output or DEST, *dates, include_funding=not args.exclude_funding)
