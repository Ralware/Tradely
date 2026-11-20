"""Build the fixed BTCUSDT USD-M research snapshot from Binance public history."""

import hashlib
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pandas as pd

DEST = Path(__file__).parent / "data" / "BTCUSDT_USDM"
START, END = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2026-01-01", tz="UTC")


HISTORY_START = pd.Timestamp("2020-01-01", tz="UTC")


def month_data(month):
    name = f"BTCUSDT-2h-{month:%Y-%m}.zip"
    url = f"https://data.binance.vision/data/futures/um/monthly/klines/BTCUSDT/2h/{name}"
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


def build():
    with ThreadPoolExecutor(4) as pool:
        parts = list(pool.map(month_data, pd.date_range(HISTORY_START, END, freq="MS", inclusive="left")))
    bars = pd.concat([data for data, _ in parts])
    expected = pd.date_range(HISTORY_START, END, freq="2h", inclusive="left")
    if not bars.index.equals(expected):
        raise ValueError("Incomplete or unordered candle history")
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    cursor, end = START.value // 10**6, END.value // 10**6
    events = []
    while cursor < end:
        page = (
            httpx.get(
                url,
                params=dict(symbol="BTCUSDT", startTime=cursor, endTime=end - 1, limit=1000),
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
    expected_events = pd.date_range(START, END, freq="8h", inclusive="left")
    if not stamps.floor("h").equals(expected_events):
        raise ValueError("Unexpected funding history coverage")
    DEST.mkdir(exist_ok=True)
    for interval, name in [("2h", "2hours"), ("4h", "4hours"), ("1D", "1day"), ("7D", "1week")]:
        res = bars.resample(interval, origin=pd.Timestamp("1970-01-05", tz="UTC"))
        frame = res.agg(dict(open="first", high="max", low="min", close="last", volume="sum"))
        frame = frame[res.size() == pd.Timedelta(interval) / pd.Timedelta("2h")].copy()
        # Binance's scheduled settlement is on the hour. Retain the exchange
        # publication time in the provenance file. Record USD paid per long unit.
        opened = dict.fromkeys(frame.index, 0.0)
        inside = opened.copy()
        for t, e in zip(stamps.floor("h"), events):
            i = frame.index.searchsorted(t, side="right") - 1
            if i >= 0 and t < frame.index[i] + pd.Timedelta(interval):
                payment = float(e["fundingRate"]) * float(e["markPrice"])
                (opened if t == frame.index[i] else inside)[frame.index[i]] += payment
        frame["funding_open_per_unit"] = opened.values()
        frame["funding_inside_per_unit"] = inside.values()
        frame["warmup_only"] = (frame.index < START).astype(int)
        frame.insert(0, "timestamp", frame.index.as_unit("ms").asi8)
        frame.to_csv(DEST / f"BTCUSDT_{name}.csv", index=False)
    (DEST / "sources.json").write_text(
        json.dumps(
            dict(
                warmup_start=str(HISTORY_START),
                start=str(START),
                cutoff=str(END),
                symbol="BTCUSDT",
                market="Binance USD-M perpetual",
                archives=[record for _, record in parts],
                funding_endpoint=url,
                funding_events=events,
            ),
            separators=(",", ":"),
        ),
        encoding="utf8",
    )


if __name__ == "__main__":
    build()
