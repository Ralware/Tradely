# Tradely — Frontend Migration Report

Date: 13 November 2026
Scope: migrate the browser UI to React + TypeScript + Vite + Tailwind while keeping the Python FastAPI backend, its API contracts and every financial calculation unchanged.

---

## 1. Outcome

| Acceptance item | Result |
|---|---|
| React frontend runs | Yes — Vite dev server on `http://localhost:5173` |
| TypeScript strict compilation | Passes (`tsc -b`, no errors) |
| Vite production build | Passes — `frontend/dist/` written in ~5.2 s |
| Tailwind CSS | Active (custom terminal palette, utilities compiled into `dist`) |
| FastAPI backend operational | Yes — `http://127.0.0.1:8000`, `/docs` available |
| Existing API contracts preserved | Yes — only one additive read-only route |
| Financial calculations unchanged | Yes — indicator/signal/backtest/risk code untouched |
| Signals unchanged for identical inputs | Yes — `/analysis` output identical to the pre-migration baseline |
| Existing data preserved | Yes — same `data/tradely.sqlite3`; watchlist/transactions/positions unchanged |
| Original features accessible | Yes — plus UI for backend features the old page did not expose |
| No mock data | Yes — failures surface the backend `detail` message |
| Windows startup script | Yes — cold start and reuse paths both verified |
| Backend regression tests | 32 passed |
| Frontend functionality verified | Yes — all routes and key interactions exercised in the browser |

---

## 2. Audit phase (completed before migration)

- `audit/ENDPOINT_INVENTORY.md` — every route, method, input, response shape, purpose and intended React consumer.
- `audit/baseline/` — pre-migration snapshots captured from the running backend:
  - `_api_health.json`, `_api_providers_status.json`, `_api_watchlist.json`
  - `_api_portfolio_transactions.json`, `_api_portfolio_positions.json`
  - `_api_signals_history.json`
  - `analysis_RELIANCE.json` (500-day request, 300 candles, all indicators, strategy state)
  - `backtest_RELIANCE.json` (1,825-day trend-breakout run)
- Legacy UI review: the old page at `backend/app/web/index.html` covered analysis, candles, indicators, strategy, news, events, watchlist and provider status only. Portfolio, backtesting, crypto market metadata, risk sizing and signal history existed in the backend but had no UI. Those are now exposed rather than removed.
- Root cause of the earlier "site not loading" problem: Python 3.15 selected by the launcher → no pandas wheel → `pip` failed → `uvicorn` missing. Fixed in the previous pass by pinning Python 3.11–3.14 in `run.bat`/`run.sh`, `requirements.txt` and `pyproject.toml`.

---

## 3. Backend changes

### 3.1 The only code change: one additive endpoint

`backend/app/api/routes.py` now includes:

```python
@router.get("/instruments/{symbol}/indicators")
def indicator_series(
    request: Request,
    symbol: str,
    market: str = Query("india", pattern="^(india|global|crypto)$"),
    exchange: str | None = None,
    interval: str = "1d",
    days: int = Query(500, ge=1, le=3650),
    provider: str = "auto",
    limit: int = Query(300, ge=50, le=1000),
) -> dict[str, Any]:
    ...
    indicators = compute_indicators(frame)
    records = _to_json_records(indicators, limit=limit)
    return {...}
```

**Why it was necessary:** the required charts include per-bar RSI and MACD panes. The existing `/analysis` endpoint returns only the latest indicator row. Reconstructing RSI/MACD in TypeScript would duplicate backend mathematics, which the brief forbids. This route returns the per-bar series directly from the existing `compute_indicators` function.

**Why it is safe:**

- It is a new route only. No existing route, request model, response model, threshold or formula was edited.
- It calls the same `compute_indicators` and `_to_json_records` helpers used by `/analysis`.
- It is read-only and writes nothing to SQLite.
- It is covered by a new test that asserts the route is additive and returns backend-computed `sma_200`/`rsi_14` values.

### 3.2 Test addition

`backend/tests/test_api.py` adds `test_indicator_series_is_additive_and_uses_backend_calculations`, which stubs the market service, requests `limit=120`, and checks the count, source, adjustment flag, last close and indicator columns.

### 3.3 Configuration only (no code)

- `.env` / `.env.example`: `PORT=8765` → `PORT=8000` with a comment that binding comes from the uvicorn CLI (`run.bat` passes `--port 8000`). The setting was already informational.
- `requirements.txt` / `pyproject.toml` already carried the Python `>=3.11,<3.15` constraint from the earlier launcher fix; no further dependency changes.

### 3.4 Explicitly unchanged

- `backend/app/main.py`, `core/*`, `providers/*`, `services/indicators.py`, `services/strategy.py`, `services/backtest.py`, `services/market.py`, database models and schema.
- Every existing route and response field.
- `backend/app/web/index.html` (legacy page retained at `/` as a fallback).
- `data/tradely.sqlite3` and its records.

---

## 4. Files created

### Frontend configuration

| File | Purpose |
|---|---|
| `frontend/package.json`, `package-lock.json` | React 19, TypeScript 5.9, Vite 7, Tailwind 3, Lightweight Charts 5, React Router 7 |
| `frontend/tsconfig.json`, `tsconfig.app.json`, `tsconfig.node.json` | Strict TypeScript project references |
| `frontend/vite.config.ts` | Dev server 5173, `/api` proxy to `127.0.0.1:8000`, production chunking |
| `frontend/tailwind.config.js`, `postcss.config.js` | Terminal palette, typography, panel shadow |
| `frontend/index.html` | Vite entry document |
| `frontend/.env.example` | Documents `VITE_API_BASE_URL` (empty = same-origin proxy) |

### Frontend source (58 files, ~5,570 lines)

| Area | Files |
|---|---|
| Entry | `src/main.tsx`, `src/App.tsx`, `src/vite-env.d.ts` |
| Types | `src/types/api.ts` — every backend response interface, no `any` |
| Services | `api.ts` (fetch wrapper, timeout, cancellation, `ApiError`), `marketService.ts`, `analysisService.ts`, `newsService.ts`, `portfolioService.ts`, `backtestService.ts`, `riskService.ts` |
| State | `hooks/useApi.ts`, `contexts/ApiStatusContext.tsx` |
| Utils / styles | `utils/format.ts`, `utils/navigation.ts`, `styles/index.css` |
| Layout | `components/layout/AppShell.tsx`, `Sidebar.tsx`, `TopBar.tsx` |
| Common | `Icon`, `Button`, `Badge`, `Card`, `Field` (Input/Select/Textarea), `States` (Spinner/LoadingPanel/EmptyState/ErrorState/Notice), `Stat`/`KeyValue`, `Tabs`, `PageHeader` |
| Charts | `PriceChart.tsx` (Lightweight Charts candles/volume/RSI/MACD), `TimeSeriesChart.tsx` (SVG equity/drawdown), `IndicatorPanel.tsx` |
| Signals | `SignalBadge`, `ConditionList`, `SignalCard`, `RiskCalculator` |
| Tables | `CandleTable`, `IndicatorTable`, `WatchlistTable`, `ScannerTable`, `PositionsTable`, `TransactionsTable`, `TradesTable`, `NewsList`, `EventsList`, `ProviderList`, `CryptoMarketsTable` |
| Analysis | `InstrumentForm`, `AnalysisWorkspace`, `FundamentalsPanel`, `SecFilingsPanel` |
| Pages | `DashboardPage`, `MarketsPage`, `StockAnalysisPage`, `CryptoAnalysisPage`, `PortfolioPage`, `BacktestingPage`, `SettingsPage`, `NotFoundPage` |

### Audit and documentation

- `audit/ENDPOINT_INVENTORY.md`
- `audit/baseline/*` (8 snapshot files)
- `MIGRATION_REPORT.md` (this file)

---

## 5. Files modified

| File | Change |
|---|---|
| `backend/app/api/routes.py` | Added `GET /api/instruments/{symbol}/indicators` |
| `backend/tests/test_api.py` | Added one additive-endpoint test |
| `run.bat` | Rewritten: Python + Node/npm checks, venv reuse, dependency install, dual server start, readiness polling, browser open, readable failure handling |
| `run.sh` | Mirrored the dual-server behaviour for Linux/macOS |
| `README.md` | Run instructions, ports, frontend architecture, production serving, endpoint table |
| `.env`, `.env.example` | `PORT` set to 8000 (informational) |

Prior-pass changes retained: `requirements.txt`, `pyproject.toml` (Python `>=3.11,<3.15`).

---

## 6. Feature migration

| Feature | Status | Where |
|---|---|---|
| Market dashboard | Migrated + extended | `/` |
| India / Global / Crypto tabs | New UI over existing endpoints | `/markets` |
| Watchlist add/remove | Migrated | `/markets`, analysis pages |
| Daily scanner | New UI over `/api/scanner/watchlist` | `/`, `/markets` |
| Stock analysis | Migrated | `/stocks` |
| Crypto analysis | Migrated | `/crypto` |
| Candlestick + volume chart | New (Lightweight Charts) | analysis pages |
| SMA/EMA/Bollinger overlays | New (latest backend values) | analysis pages |
| RSI / MACD panes | New (per-bar backend series) | analysis pages |
| Indicator panel + full table | Migrated + visualised | analysis pages |
| BUY/SELL/HOLD signal with explanation | Migrated | analysis pages |
| Entry / stop / risk per unit | Migrated | signal card |
| Position sizing | New UI over `POST /api/risk/position-size` | analysis pages |
| News | Migrated | analysis pages |
| Corporate events + official links | Migrated | analysis pages |
| Fundamentals | New UI over existing endpoint | stock analysis |
| SEC EDGAR filings | New UI over existing endpoint | stock analysis (global) |
| Crypto market metadata | New UI over existing endpoint | `/markets` (Crypto) |
| Portfolio transactions | New UI over existing endpoint | `/portfolio` |
| FIFO positions / realised P&L | New UI over existing endpoint | `/portfolio` |
| Backtesting form | New UI over existing endpoint | `/backtesting` |
| Metrics, equity curve, drawdown, trades | New UI | `/backtesting` |
| Signal audit history | New UI over existing endpoint | `/settings`, `/` |
| Provider status + health | Migrated | `/`, `/settings` |
| Legacy plain-HTML page | Retained unchanged | `http://127.0.0.1:8000/` |

Charts only visualise backend values. The one derived visual is the underwater drawdown curve, computed from the backend's `equity_curve` points for display; the headline `max_drawdown_pct` is backend-computed and labelled as such.

---

## 7. Test and build results (actual)

### Backend

```text
32 passed, 10 warnings in 1.91s
```

Was 31 before the additive endpoint test; the new test passes. Warnings are pre-existing NumPy `timedelta` deprecations in provider/indicator code, not failures.

### Frontend

```text
npx tsc -b        → exit 0, no diagnostics
npm run build     → ✓ 100 modules transformed, built in 5.22s
```

Production bundle:

```text
dist/index.html                  0.76 kB
dist/assets/index-*.css         21.59 kB │ gzip 5.07 kB
dist/assets/react-*.js          50.33 kB │ gzip 17.81 kB
dist/assets/charts-*.js        172.53 kB │ gzip 55.76 kB
dist/assets/index-*.js         312.58 kB │ gzip 92.63 kB
```

### Browser verification (Vite + FastAPI running)

| Check | Result |
|---|---|
| `/` dashboard | Loads; health, watchlist, scanner, positions, signal history, providers render; no console errors |
| `/markets` (India/Global/Crypto) | Tabs switch; add form validates; watchlist/scanner render; crypto tab shows the backend 503 message when CoinGecko is unconfigured |
| `/stocks?symbol=RELIANCE…` | Analysis, 300 candles, 7 chart canvases, all indicators, WAIT signal with 7 rule checks, news, events, fundamentals prompt |
| `/crypto?symbol=BTCUSDT…` | Binance candles, SELL signal, charts and indicator series render |
| `/portfolio` | Positions, transactions, accounting method render; client-side validation rejects an empty symbol |
| `/backtesting` | POST runs; metrics, equity curve, drawdown curve, 4 trades and limitations render |
| `/settings` | Health, provider state, config values, docs links, signal audit table |
| Unknown route | 404 page renders |
| Risk calculator | POST `/api/risk/position-size` returns 500 risk budget / 12 units for the test inputs |
| Console | No uncaught JS errors; only expected network log for the CoinGecko 503 |

### Regression comparison against `audit/baseline/`

| Endpoint | Result |
|---|---|
| `/api/instruments/RELIANCE/analysis` | Latest OHLCV **identical**, all 31 indicator values **identical**, strategy state (`WAIT`) **identical**, condition list **identical**, 300 candles **identical** |
| `/api/portfolio/positions` | **Identical** (0 positions, same accounting method) |
| `/api/portfolio/transactions` | **Identical** (0 rows) |
| `/api/watchlist` | **Identical** (0 items) |
| `/api/providers/status` | **Identical** |
| `/api/backtests/trend-breakout` | Same 4 trades, same entry/exit timestamps, quantities and exit reasons. Net return 0.7778813883125846% → 0.7778786573725327% |

The backtest difference is upstream data, not code: entry/exit prices moved by at most 1.2 × 10⁻⁴ because `yfinance` revised older adjusted closes between the baseline capture and the rerun. Two consecutive reruns after the revision are bit-identical, and the 300 most recent candles (the `/analysis` window) match the baseline exactly. No strategy, indicator or execution code changed.

---

## 8. Runtime and deployment

- Development: FastAPI `127.0.0.1:8000`, Vite `127.0.0.1:5173`, `/api` proxied by Vite (no CORS change needed).
- `run.bat`: verifies Python and Node/npm, recreates an incompatible `.venv`, installs missing Python and frontend dependencies, starts both servers in separate windows, polls readiness, reuses already-running services, opens the browser, and pauses with a readable message on failure. Both the cold-start and reuse paths were executed successfully.
- Production: `npm run build` writes `frontend/dist/`. Serve that directory from any static host and reverse-proxy `/api` to FastAPI, or set `VITE_API_BASE_URL` to an absolute backend origin and enable CORS. `npm run preview` provides a local preview on port 4173 with the same proxy.

---

## 9. Outstanding issues and honest limitations

1. **CoinGecko metadata requires a key.** Without `COINGECKO_API_KEY`, `/api/crypto/markets` returns 503 and the Markets crypto tab shows that exact message. Crypto analysis still works through Binance.
2. **No instrument-search endpoint.** Symbol entry is explicit by design; the UI does not fabricate a ticker database. The top-bar search is a symbol shortcut, not a lookup.
3. **Fundamentals and SEC filings need provider configuration.** The UI loads them on demand and shows provider errors verbatim.
4. **Provider revisions can move historical prices.** Backtests over long histories may differ slightly between runs when an upstream adjusted series is revised. The backend reports its source and adjustment flag; the UI displays them.
5. **No automated frontend unit/E2E suite.** Verification was strict type-checking, a production build, and browser checks across every route and key interaction. No test runner was added to avoid expanding the dependency surface beyond the brief.
6. **No frontend recalculation of financial values.** The only derived display value is the underwater drawdown curve from backend equity points, clearly labelled; headline risk, signal, indicator and backtest metrics all come from the backend.
7. **Legacy page retained.** `/` on the backend still serves the old plain-HTML workbench; the React app is the primary UI at `http://localhost:5173`.
8. **Bundle size.** React, router and Lightweight Charts are split into separate chunks; the largest chunk is ~313 kB (93 kB gzip), acceptable for a local tool.

---

## 10. How to run

```bat
run.bat
```

Then open `http://localhost:5173` (opened automatically). API docs: `http://127.0.0.1:8000/docs`.

Manual alternative and production notes are in `README.md`.
