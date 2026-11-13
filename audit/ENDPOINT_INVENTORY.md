# Tradely — Endpoint Inventory (pre-migration audit)

Audited: 13 November 2026
Backend entry point: `backend/app/main.py` → `app.api.routes.router` (prefix `/api`)
Base URL in development after migration: `http://127.0.0.1:8000`
Default URL before migration: `http://127.0.0.1:8765`

All financial calculations stay in the backend. The React frontend only renders
values returned by these endpoints.

| Endpoint | Method | Input | Output (top-level shape) | Purpose | Frontend usage |
|---|---|---|---|---|---|
| `/` | GET | — | `text/html` (`backend/app/web/index.html`) | Legacy workbench page (retained unchanged as fallback) | Not used by React; Vite serves the new UI |
| `/assets/*` | GET | path | static files | Static mount for the legacy page | Not used by React |
| `/docs`, `/openapi.json` | GET | — | Swagger UI / OpenAPI JSON | API documentation | Linked from Settings |
| `/api/health` | GET | — | `{status, application, mode, ai, paper_trading, order_execution, timestamp}` | Liveness + scope flags | Top bar status, Dashboard, Settings |
| `/api/providers/status` | GET | — | `{providers: [{name, configured, note}], checked_at}` | Provider configuration state | Dashboard, Settings |
| `/api/market/candles` | GET | `symbol`, `market` (india/global/crypto), `exchange?`, `interval` (default `1d`), `days` (1–3650, default 365), `provider` (auto/tejhq/yahoo/binance) | `{symbol, market, exchange, interval, source, is_adjusted, freshness, is_stale, history_truncated, history_pages, last_candle_at, count, candles[], warnings[]}` | Normalised OHLCV | `marketService.getCandles`; candle table / chart |
| `/api/scanner/watchlist` | GET | — | `{items: [{symbol, market, source, last_close, is_adjusted, is_stale, strategy}], count, note}` | Daily strategy scan of saved watchlist | Dashboard, Markets |
| `/api/instruments/{symbol}/analysis` | GET | `symbol`, `market`, `exchange?`, `interval`, `days` (default 500), `provider` | `{symbol, market, exchange, interval, source, is_adjusted, is_stale, history_truncated, history_pages, as_of, latest{open,high,low,close,volume}, indicators{...}, strategy, warnings[], candles[]}` | Indicators + strategy signal + 300 candles | StockAnalysis, CryptoAnalysis |
| `/api/instruments/{symbol}/indicators` **(added)** | GET | same as analysis + `limit` (50–1000, default 300) | `{symbol, market, exchange, interval, source, is_adjusted, is_stale, as_of, count, series[]}` where each series row contains OHLCV + every indicator column | Per-bar indicator series for charts. **Additive only**; reuses `compute_indicators`, no formula change | StockAnalysis / CryptoAnalysis chart panes |
| `/api/instruments/{symbol}/fundamentals` | GET | `symbol`, `market`, `exchange?` | `{symbol, source, profile{}, quarterly_income_statement, quarterly_balance_sheet, quarterly_cash_flow, limitations[]}` | Best-effort Yahoo profile/statements | StockAnalysis (fundamentals tab) |
| `/api/instruments/{symbol}/news` | GET | `symbol`, `market`, `company_name?`, `limit` (1–50) | `{symbol, market, items[], count, providers{}, note}` | GDELT + RSS + Yahoo news discovery | StockAnalysis, CryptoAnalysis |
| `/api/instruments/{symbol}/events` | GET | `symbol`, `market` | `{symbol, market, events[], official_source_links[], provider_error, note}` | Corporate actions + official links | StockAnalysis, CryptoAnalysis |
| `/api/us/issuers/{cik}/filings` | GET | `cik` path | `{cik, items[], count}` | SEC EDGAR filings | StockAnalysis (global market) |
| `/api/crypto/markets` | GET | `symbols?` (comma list) | `{source, markets[]}` | CoinGecko Demo market metadata | Markets, CryptoAnalysis |
| `/api/backtests/trend-breakout` | POST | JSON `{symbol, market, exchange?, interval (must be 1d), days (240–3650), provider, initial_capital, risk_fraction (≤0.02), cost_bps_per_side, max_position_fraction}` | `{initial_capital, final_equity, net_return_pct, trade_count, win_rate_pct, profit_factor, expectancy_per_trade, max_drawdown_pct, sharpe_daily_annualized, sortino_daily_annualized, cost_bps_per_side, trades[], equity_curve[], limitations[], symbol, market, source, strategy, strategy_version, data_adjusted}` | Single-instrument research backtest | Backtesting |
| `/api/risk/position-size` | POST | JSON `{capital, risk_fraction (≤0.02), entry, stop, lot_size, max_position_fraction}` | `{risk_budget, risk_per_unit, quantity, position_value, planned_loss, capital_limited}` | ATR/stop position sizing | StockAnalysis, CryptoAnalysis risk calculator |
| `/api/signals/history` | GET | `limit` (1–500) | `{signals[]}` | Signal audit history | Settings |
| `/api/watchlist` | GET | — | `{items[]}` | Read watchlist | Dashboard, Markets |
| `/api/watchlist` | POST | JSON `{symbol, market, exchange?, display_name?}` | watchlist row | Add watchlist entry | Dashboard, analysis pages |
| `/api/watchlist/{market}/{symbol}` | DELETE | `market`, `symbol`, `exchange?` query | `{removed}` | Remove watchlist entry | Dashboard, Markets |
| `/api/portfolio/transactions` | GET | — | `{transactions[], mode}` | Actual-holdings ledger | Portfolio |
| `/api/portfolio/transactions` | POST | JSON `{symbol, market, side (BUY/SELL), quantity, price, trade_time, currency, fees, notes?}` | transaction row | Record a real trade | Portfolio |
| `/api/portfolio/positions` | GET | — | `{positions[{market, symbol, currency, quantity, cost_basis, realised_pnl, average_cost}], accounting_method, note}` | FIFO open positions | Portfolio |

## Error contract

All handlers raise `HTTPException`; FastAPI returns `{"detail": "<message>"}` with
status `422` (validation/business rule), `502` (provider failure) or `503`
(provider not configured). The frontend surfaces `detail` verbatim and never
substitutes mock data.

## Notes discovered during audit

- `signal_audit` is appended on every `/analysis` request.
- `/news` and `/events` can take up to the configured HTTP timeout (15 s) when
  upstream providers are slow; the UI renders the rest of the page first.
- `/api/scanner/watchlist` returns a per-item `error` field instead of failing
  the whole request when one symbol fails.
- The backend exposes **no** instrument-search endpoint (documented limitation in
  the README). Search in the UI is an explicit symbol/market form, not a
  fabricated ticker database.
- `PORT` in `.env` is informational; the bind address comes from the uvicorn
  command line.
