# Tradely — Endpoint Inventory

Audited: 14 November 2026

The React application is the maintained frontend. In production, FastAPI serves `frontend/dist/index.html` at `/` and its assets at `/assets/*`; Vite continues to serve the frontend and proxy `/api` during development.

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/health` | GET | Application status and scope flags |
| `/api/providers/status` | GET | Availability, purpose, and configuration state for TejHQ adjusted/raw OHLCV, Yahoo Finance, Binance Spot, GDELT, and Yahoo Finance News |
| `/api/market/candles` | GET | Normalised OHLCV, source attribution, adjustment state, and freshness |
| `/api/scanner/watchlist` | GET | Daily deterministic strategy scan of the saved watchlist |
| `/api/instruments/{symbol}/analysis` | GET | Indicators, strategy signal, data-quality warnings, and completed candles |
| `/api/instruments/{symbol}/indicators` | GET | Per-bar indicator values for charts |
| `/api/instruments/{symbol}/technicals` | GET | Indicator-based technical summary |
| `/api/instruments/{symbol}/news` | GET | GDELT discovery with optional Yahoo Finance News supplementation |
| `/api/backtests/trend-breakout` | POST | Daily deterministic research backtest |
| `/api/risk/position-size` | POST | Local position sizing calculation |
| `/api/signals/history` | GET | Saved signal audit history |
| `/api/watchlist` | GET, POST | Read and maintain local watchlist entries |
| `/api/watchlist/{market}/{symbol}` | DELETE | Remove a local watchlist entry |
| `/api/portfolio/transactions` | GET, POST | Local transaction ledger |
| `/api/portfolio/positions` | GET | Local FIFO positions and realised P&L |

Removed routes: `/api/crypto/markets`, `/api/instruments/{symbol}/fundamentals`, `/api/instruments/{symbol}/events`, and `/api/us/issuers/{cik}/filings`.

Provider routing is deterministic: India uses TejHQ, international equities use the unofficial Yahoo Finance adapter, and crypto uses Binance Spot public market-data endpoints. Indian raw history is explicitly unadjusted and cannot create actionable signals or backtests. News responses are deduplicated by canonical URL and cached; a failure from one retained news provider does not prevent records from the other.
