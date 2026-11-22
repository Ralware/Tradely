# Tradely

Private, local-first quantitative market analysis for Indian equities, international
equities and cryptocurrency. Tradely computes indicators, rule-based signals,
risk sizing, a daily backtest and FIFO portfolio accounting in a Python backend,
and renders them in a React application.

Tradely does not place orders, run paper trading, use AI predictions or bundle a
news provider. All market data comes from the unofficial TradingView API through
a loopback Node.js bridge.

## Architecture

```text
backend/
  app/
    api/routes.py          FastAPI routes
    core/                  settings, SQLite database, models, instruments, trading rules
    instruments/           canonical identity, resolver, search, catalogue, capabilities
    providers/             TradingView bridge client and candle normalisation
    services/              market data, quotes, indicators, strategy, backtest, portfolio
  tests/                   pytest suite
frontend/
  src/
    components/            analysis, charts, common, layout, portfolio, signals, tables
    contexts/              URL-driven selected-instrument provider
    hooks/                 typed API hook and shared quote subscription
    pages/                 Watchlist, Analysis, Portfolio, Backtesting, NotFound
    services/              typed API layer and quote hub (REST + SSE)
    types/                 backend response interfaces
    utils/                 formatting, quote labels, navigation, timeframes, transaction maths
tradingview-bridge/
  server.mjs               read-only HTTP bridge over the bundled TradingView library
TradingView-API/
  TradingView-API-main/    vendored unofficial TradingView Node.js library
                           (source, build config and licence only; dist/ is built on demand)
```

The vendored library is [TradingView-API](https://github.com/Mathieu2301/TradingView-API)
by Mathieu Colmon, used under the ISC licence reproduced in its `LICENSE` file.
Only `src/`, the TypeScript build configuration and the package manifests are
vendored; upstream documentation, tests, examples, scripts, assets and tooling
are not part of this repository.

The FastAPI process serves the API under `/api` and, when `frontend/dist/`
exists, the production React bundle at `/` (client-side routes fall back to
`index.html`). During development Vite proxies `/api` to FastAPI.

### Analytics precomputation migration

Tradely now has an additive SQLite-backed analytics job queue, compressed and
checksummed prepared snapshots, a background worker started with FastAPI,
read-only prepared-data endpoints, and an application-start frontend hydrator
using IndexedDB plus a reactive in-memory store. Analytics navigation and
timeframe switching consume already-hydrated snapshots; manual refresh queues
work rather than running the analytics pipeline inline. The legacy
`/analytics-snapshot` endpoint remains for backward compatibility during this
migration and is still synchronous. See
[`docs/ANALYTICS_PRECOMPUTATION.md`](docs/ANALYTICS_PRECOMPUTATION.md) for schema,
operations, testing and explicitly identified remaining work.

## Requirements

- Python 3.11, 3.12, 3.13 or 3.14 (Python 3.15 is unsupported until pandas ships
  a wheel).
- Node.js 20 or newer with npm.

## Run

One command on Windows:

```bat
run.bat
```

On Linux/macOS:

```bash
./run.sh
```

The launcher creates or reuses `.venv`, installs backend and frontend
dependencies, builds the bundled TradingView library when `dist/` is absent,
starts the bridge on `127.0.0.1:8010`, FastAPI on `127.0.0.1:8000` and Vite on
`localhost:5173`, and reuses services that are already running.

Manual setup:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env

# Terminal 1
cd tradingview-bridge
npm start

# Terminal 2
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# Terminal 3
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. API documentation is available at
`http://127.0.0.1:8000/docs`.

## Configuration

Settings are read from the repository-root `.env` (see `.env.example`). The
backend binds to loopback only; `HOST` values other than `127.0.0.1`, `localhost`
or `::1` are rejected at startup.

| Variable                              | Default                  | Purpose                                           |
| ------------------------------------- | ------------------------ | ------------------------------------------------- |
| `HOST`                                | `127.0.0.1`              | FastAPI bind address (loopback only)              |
| `DATABASE_PATH`                       | `./data/tradely.sqlite3` | SQLite file location                              |
| `TRADINGVIEW_BRIDGE_URL`              | `http://127.0.0.1:8010`  | Loopback bridge origin                            |
| `TRADINGVIEW_BRIDGE_TIMEOUT_SECONDS`  | `60`                     | Bridge request timeout                            |
| `TRADINGVIEW_CANDLES_TIMEOUT_SECONDS` | `50`                     | Candle request timeout                            |
| `TRADINGVIEW_QUOTES_TIMEOUT_SECONDS`  | `30`                     | Quote request timeout                             |
| `TRADINGVIEW_SEARCH_TIMEOUT_SECONDS`  | `15`                     | Search request timeout                            |
| `TRADINGVIEW_LIVE_SEARCH_ENABLED`     | `true`                   | Allow live TradingView search for unknown symbols |
| `MARKET_CACHE_SECONDS`                | `300`                    | Candle cache lifetime                             |
| `QUOTE_CRYPTO_TTL_SECONDS`            | `10`                     | Crypto quote cache                                |
| `QUOTE_GLOBAL_TTL_SECONDS`            | `300`                    | Global equity quote cache                         |
| `QUOTE_INDIA_TTL_SECONDS`             | `600`                    | Indian equity quote cache                         |
| `QUOTE_BACKOFF_BASE_SECONDS`          | `5`                      | Provider backoff base                             |
| `QUOTE_BACKOFF_MAX_SECONDS`           | `300`                    | Provider backoff ceiling                          |
| `QUOTE_STREAM_INTERVAL_SECONDS`       | `5`                      | SSE replay interval                               |
| `DEFAULT_ACCOUNT_CURRENCY`            | `INR`                    | Reporting currency for risk sizing                |
| `MAX_RISK_FRACTION`                   | `0.02`                   | Maximum accepted risk fraction                    |

Optional `TRADINGVIEW_SESSION` and `TRADINGVIEW_SIGNATURE` cookies are read by the
bridge for account data. Leave them empty for anonymous access. Credentials stay
in `.env`, which is git-ignored and never sent to the browser.

## API

| Method       | Route                                          | Purpose                                                |
| ------------ | ---------------------------------------------- | ------------------------------------------------------ |
| `GET`        | `/api/health`                                  | App status and scope flags                             |
| `GET`        | `/api/providers/status`                        | Bridge health and provider limits                      |
| `GET`        | `/api/market/candles`                          | Normalised OHLCV candles                               |
| `GET`        | `/api/scanner/watchlist`                       | Daily strategy scan of the saved watchlist             |
| `GET`        | `/api/instruments/search`                      | Catalogue plus live TradingView search                 |
| `GET`        | `/api/instruments/resolve`                     | Resolve a query to canonical identity                  |
| `GET`        | `/api/instruments/{instrument_id}`             | Stored instrument metadata and capabilities            |
| `GET`        | `/api/instruments/{symbol}/analysis`           | Indicators, strategy signal and candles                |
| `GET`        | `/api/instruments/{symbol}/indicators`         | Per-bar indicator series for charts                    |
| `GET`        | `/api/instruments/{symbol}/technicals`         | Conventional Buy/Sell/Neutral labels                   |
| `GET`        | `/api/instruments/{symbol}/news`               | Explicit empty result (no news provider)               |
| `POST`       | `/api/backtests/trend-breakout`                | Daily single-instrument backtest                       |
| `POST`       | `/api/risk/position-size`                      | Direction-aware position sizing                        |
| `GET`/`POST` | `/api/watchlist`                               | Read or add watchlist entries                          |
| `DELETE`     | `/api/watchlist/instruments/{instrument_id}`   | Remove by canonical identity                           |
| `DELETE`     | `/api/watchlist/{market}/{symbol}`             | Remove by legacy identity                              |
| `GET`        | `/api/market/quotes`                           | Deduplicated quotes by instrument, symbol or watchlist |
| `GET`        | `/api/market/quotes/stream`                    | SSE replay of the shared quote cache                   |
| `GET`/`POST` | `/api/portfolio/transactions`                  | Ledger rows and amount-based entries                   |
| `POST`       | `/api/portfolio/transactions/preview`          | Server-authoritative quantity preview                  |
| `DELETE`     | `/api/portfolio/transactions/{transaction_id}` | Delete a row if the ledger stays valid                 |
| `GET`        | `/api/portfolio/summary`                       | Currency-separated valuation and P&L                   |
| `GET`        | `/api/portfolio/positions`                     | Open positions with backend valuation                  |
| `GET`        | `/api/portfolio/positions/{instrument_id}`     | Position detail, ledger history and candles            |

## Behaviour

- **Identity.** Every instrument uses `market:EXCHANGE:SYMBOL`
  (for example `india:NSE:RELIANCE`, `global:NASDAQ:AAPL`,
  `crypto:BINANCE:BTCUSDT`). The URL `instrument` parameter is authoritative for
  the Analysis page; legacy `symbol`/`market`/`exchange` parameters are
  normalised to it.
- **Market data.** Candles are split-adjusted and the still-forming final bar is
  dropped. Analysis, chart and history views request all bars TradingView exposes
  for the timeframe; date-bounded requests pass an explicit range. Canonical
  intervals include `1wk` and `1mo`.
- **Signals.** One versioned daily trend/Donchian strategy supports long-only,
  short-only and long/short backtests. Signals are suppressed with `STALE_DATA` or
  `DATA_QUALITY_ERROR` when candles are stale or Indian history is not confirmed
  as split-adjusted.
- **Indicators.** SMA, EMA, Wilder RSI/ATR/ADX, MACD, Bollinger Bands, Donchian
  channels, relative volume, OBV, session VWAP (intraday only), MFI, CMF, CCI and
  Stochastic RSI are computed in the backend. The frontend renders backend values
  and never calculates its own.
- **Quotes.** One shared quote service batches TradingView requests, deduplicates
  instruments, caches per market and backs off on provider errors. The SSE
  endpoint replays this cache; it is not a socket feed. TradingView delay fields
  drive `real_time`/`delayed` labels; anonymous NSE data is typically 15 minutes
  delayed.
- **Portfolio.** Amount-based BUY, SELL, SELL_SHORT and BUY_TO_COVER entries use a
  validated provider quote to derive quantity and store a reference price. FIFO
  long and short lots, fees, realised/unrealised P&L and currency-separated
  summaries are calculated by the backend. No currency conversion, order
  execution, borrowing or paper trading is implied.
- **Backups.** The SQLite database is user data. Keep copies outside this
  repository; the app never deletes or recreates it.

## Tests and builds

```bash
# backend (from the repository root)
.\.venv\Scripts\python.exe -m pytest -q

# frontend
cd frontend
npm.cmd test
npm.cmd run typecheck
npm.cmd run build
```

`npm run build` writes the production bundle to `frontend/dist/`. FastAPI serves
that directory when present.

## Known limits

- TradingView is an unofficial community API. Availability, delay and history
  depth can change without notice.
- The backtest is a single-instrument model with next-bar-open
  execution and aggregate basis-point costs. It is not a portfolio simulator,
  tax engine or proof of profitability. Position size is fractional so every
  positive capital value is usable; venues that require whole shares will differ.
- News, fundamentals, corporate events, currency conversion and remote access
  are not implemented. `/api/instruments/{symbol}/news` returns an explicit empty
  result.
- The application is intended for one owner on a private installation and is not
  a public service.
