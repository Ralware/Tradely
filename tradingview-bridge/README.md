# Tradely TradingView bridge

Tradely's backend is Python, while the bundled unofficial TradingView API is a
Node.js ESM library. This bridge imports the prebuilt library directly from
`../TradingView-API/TradingView-API-main/dist/index.js` and exposes a small,
read-only HTTP surface on loopback (`127.0.0.1:8010` by default).

It never places orders or changes a TradingView account. Every endpoint is
read-only market data.

## Run

```powershell
cd tradingview-bridge
npm start
```

`run.bat` and `run.sh` build the library if needed and start the bridge before
FastAPI.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Bridge and library status |
| `GET /candles?symbol=NSE:RELIANCE&timeframe=D&count=365` | OHLCV bars, split-adjusted by default; `count` pages until that many bars or exhaustion |
| `GET /candles?symbol=NSE:RELIANCE&timeframe=D&from=...&to=...` | OHLCV bars for an explicit Unix-seconds range |
| `GET /quotes?symbols=NSE:RELIANCE,BINANCE:BTCUSDT` | Batched quotes with per-symbol fallback |
| `GET /symbol?symbol=NSE:RELIANCE` | Symbol metadata (`pricescale`, `minmov`, session, currency) |
| `GET /search?q=RELIANCE&limit=20` | Live market search |

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `TRADINGVIEW_BRIDGE_HOST` | `127.0.0.1` | Bind address; keep loopback-only |
| `TRADINGVIEW_BRIDGE_PORT` | `8010` | Bridge port |
| `TRADINGVIEW_BRIDGE_CONCURRENCY` | `3` | Concurrent TradingView operations |
| `TRADINGVIEW_SESSION` | empty | Optional `sessionid` cookie for account data |
| `TRADINGVIEW_SIGNATURE` | empty | Optional `sessionid_sign` cookie |
| `TRADINGVIEW_CANDLE_TIMEOUT_MS` | `45000` | Per-request candle timeout |
| `TRADINGVIEW_QUOTE_TIMEOUT_MS` | `25000` | Per-request quote timeout |
| `TRADINGVIEW_SYMBOL_TIMEOUT_MS` | `25000` | Per-request symbol timeout |
| `TRADINGVIEW_SEARCH_TIMEOUT_MS` | `20000` | Per-request search timeout |

Anonymous TradingView access is delayed for many exchanges (NSE data is
typically 15 minutes delayed) and deep intraday history may be limited. Those
limits are surfaced in Tradely's provider notes instead of being hidden.
