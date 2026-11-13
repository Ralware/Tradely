# Tradely — Quantitative Trading & Market Analysis

> **A rule-based multi-market trading research and analysis platform for Indian equities, international equities and cryptocurrency assets.**  
> **No AI, no black-box predictions:** indicators, signals, risk calculations and backtests are produced by explicit mathematical rules.

**Document status:** Research and system-design specification  
**Research reviewed:** 11 November 2026  
**Deployment target:** Private, single-user installation for the owner only; not a public website, SaaS product or shared service  
**Market scope:** NSE/BSE equities, international listed equities (US first, then other exchanges where free data is available), and cryptocurrency spot assets  
**Initial trading horizon:** Daily swing trading; intraday strategies are a separately validated module. Tradely provides analysis, alerts, backtesting and manual tracking of the owner's actual holdings; it does not place orders or provide paper trading.

> **Private-use and free-data boundary:** Tradely is intended only for one person's private research on their own installation. The target is a no-subscription build using free or personal-use sources where their current terms permit that use. There is no single free, official, unrestricted API for live prices, complete fundamentals, corporate disclosures and news across NSE/BSE, every international exchange and all crypto venues. Free sources have quotas, delays, missing symbols, unofficial access paths or personal-use/licensing limits. Private use does not waive a provider's terms, rate limits, attribution requirements, exchange data rules or access controls. Tradely must not redistribute feeds or expose them to other users.

---

## Current implementation status — 11 November 2026

This repository now contains a **runnable local application foundation**, not just a product proposal. The first implementation intentionally prioritises the data model, provider boundaries, indicator arithmetic, explainable strategy logic and tests. The browser UI has been migrated to a React + TypeScript + Vite + Tailwind application in `frontend/`; the legacy plain-HTML workbench remains at `/` as a fallback. All financial calculations, API contracts and provider integrations remain in the Python backend.

### Implemented now

- FastAPI backend bound to `127.0.0.1` by default, with a startup guard that rejects non-loopback hosts.
- SQLite persistence for a single-owner watchlist, manual actual-holdings transactions and signal audit history.
- Provider adapters for TejHQ daily Indian equity data, Yahoo Finance through `yfinance`, Binance public Spot candles (paged up to 20,000 bars per fetch, with a truncation flag), CoinGecko market metadata, GDELT news, configurable RSS/Atom feeds, Yahoo Finance news through `yfinance`, TejHQ corporate actions and SEC EDGAR filings by CIK.
- OHLCV normalisation and validation, with provider/source and adjustment metadata.
- Best-effort Yahoo Finance company profiles, valuation/quality ratios and quarterly financial statements where the provider supplies them.
- Deterministic SMA, EMA, Wilder-seeded RSI/ATR/ADX, MACD, Bollinger Bands, Donchian channels, relative volume, OBV, session VWAP (intraday bars only; deliberately unavailable on daily bars), MFI, CMF, CCI and Stochastic RSI calculations.
- One versioned daily long-only trend/Donchian strategy. `BUY` means all entry conditions pass. `SELL` means exit an existing long after a close below the prior 10-bar low; it does **not** open a short.
- Signal suppression when daily strategy data is stale or Indian-equity history is not confirmed corporate-action-adjusted.
- ATR-based position sizing, a single-instrument daily backtest with next-bar-open execution assumptions and configurable aggregate basis-point costs.
- Stock/asset-specific news and event endpoints. The India events panel returns TejHQ corporate-action records plus links to official NSE/BSE announcement pages; it does not invent future board-meeting or results dates when no structured source is available.
- Manual actual-holdings transaction ledger with FIFO cost-basis and realised P&L calculations. No simulated trades, paper-trading account or order placement.
- React + TypeScript frontend with dashboard, markets/watchlist, stock and crypto analysis, portfolio (FIFO), backtesting and settings pages; candlestick/volume charts via Lightweight Charts and backend-computed indicator series; machine-readable API at `/docs`; automated unit/API tests.

### Not implemented yet (do not assume these features exist)

- A statistically approved or profitable strategy. The included backtest is an initial single-instrument research implementation, not a full portfolio simulator, survivorship-free universe test or completed walk-forward/PBO/DSR validation programme.
- Multiple strategy families as executable engines. Momentum ranking, pullback, mean reversion and intraday ORB remain research specifications until implemented and tested.
- Full point-in-time NSE/BSE constituent history, delisted-equity coverage, exchange-calendar integration, complete Indian transaction-tax calculation or a broker-specific fill model.
- Complete institutional-grade fundamentals/financial-statement coverage, ticker search/discovery and automatic international issuer-to-CIK mapping. The current Yahoo fundamentals adapter is best-effort and must be cross-checked against issuer filings.
- Structured upcoming NSE/BSE board-meeting, earnings-call and AGM feeds. The official exchange pages are linked for verification; provider-returned TejHQ corporate actions are the only structured India event feed implemented here.
- Crypto project-event discovery, smart-contract/token unlock calendar or derivatives/funding data. Crypto candles are exchange-specific Binance Spot data; CoinGecko is currently metadata/market-context enrichment only.
- Unrealised P&L from live market marks, currency conversion or broker account synchronisation. The holdings API reports recorded positions and FIFO realised P&L; it does not pretend to know a live mark when no market mark has been fetched.
- Automated notifications or remote access. Unrealised P&L from live marks, currency conversion and broker synchronisation remain out of scope.

The implementation is deliberately honest about unavailable data: provider failures are surfaced, missing event data is not filled with guesses, and a data source is not silently treated as live or adjusted. Provider adapters are replaceable; the strategy engine never imports a vendor SDK.

### Run locally

Requirements:

- Python 3.11, 3.12, 3.13 or 3.14. Python 3.15 is **not** supported yet: `pandas<3.0` has no wheel for it, so `pip install -r requirements.txt` falls back to a source build and fails without a full C/C++ toolchain. The launcher scripts select a compatible interpreter automatically when one is installed.
- Node.js 20 or newer, including npm. Node is required only for the React frontend.

#### One-command Windows launcher

```bat
run.bat
```

`run.bat` checks Python and Node/npm, creates or reuses `.venv`, installs missing Python and frontend dependencies, starts FastAPI on `http://127.0.0.1:8000` and Vite on `http://localhost:5173` in separate windows, waits until both answer, then opens `http://localhost:5173`. It reuses an already-running backend or frontend instead of starting a duplicate, and prints a readable error (with `pause`) if any step fails.

#### Manual setup

**Windows (PowerShell):**

```powershell
cd tradely
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Edit .env and add your TejHQ free key, if available.
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Then, in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

**Linux/macOS:**

```bash
cd tradely
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your TejHQ free key, if available.
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Then, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` for the React application. API documentation is at `http://127.0.0.1:8000/docs`; the legacy plain-HTML workbench remains at `http://127.0.0.1:8000/`.

Set `TEJHQ_API_KEY` to use TejHQ's adjusted-price endpoint. Without it, Tradely prefers adjusted Yahoo Finance history for Indian technical analysis and only falls back to raw TejHQ EOD if Yahoo is unavailable; **the signal is suppressed when the chosen Indian source is unadjusted**. Set `COINGECKO_API_KEY` for optional CoinGecko market metadata. Set `SEC_USER_AGENT` to a real identifying product/contact string before calling SEC EDGAR. Add permitted feed URLs to `RSS_FEED_URLS` as a comma-separated list. Provider keys stay in `.env` and must never be committed.

Run the backend tests (from the repository root):

```bash
python -m pytest
```

Type-check and build the frontend:

```bash
cd frontend
npm run typecheck
npm run build
```

The production bundle is written to `frontend/dist/`.

### Implemented API routes

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Local app status and scope flags |
| `GET` | `/api/providers/status` | Provider configuration and known limits |
| `GET` | `/api/market/candles` | Normalised OHLCV candles |
| `GET` | `/api/instruments/{symbol}/analysis` | Latest indicators and strategy explanation |
| `GET` | `/api/instruments/{symbol}/indicators` | Per-bar OHLCV plus every backend-computed indicator (additive; used for chart panes) |
| `GET` | `/api/instruments/{symbol}/fundamentals` | Best-effort profile, ratios and quarterly statements |
| `GET` | `/api/instruments/{symbol}/news` | GDELT, RSS and Yahoo news discovery |
| `GET` | `/api/instruments/{symbol}/events` | Instrument-specific corporate actions and official source links |
| `GET` | `/api/us/issuers/{cik}/filings` | SEC EDGAR filing feed by CIK |
| `GET` | `/api/crypto/markets` | CoinGecko Demo market metadata |
| `GET` | `/api/scanner/watchlist` | Daily strategy scan of saved watchlist |
| `POST` | `/api/backtests/trend-breakout` | Initial daily single-instrument backtest |
| `POST` | `/api/risk/position-size` | Risk-budget position sizing |
| `GET/POST` | `/api/watchlist` | Read/add watchlist entries |
| `DELETE` | `/api/watchlist/{market}/{symbol}` | Remove a watchlist entry |
| `GET/POST` | `/api/portfolio/transactions` | Read/add actual trade transactions |
| `GET` | `/api/portfolio/positions` | FIFO open positions and realised P&L |
| `GET` | `/api/signals/history` | Audit history of generated strategy signals |

### React frontend

The frontend lives in `frontend/` and is a separate build from the Python app.

```text
frontend/
  index.html
  package.json
  tsconfig.json / tsconfig.app.json / tsconfig.node.json
  vite.config.ts
  tailwind.config.js
  src/
    components/
      analysis/     # instrument form, analysis workspace, fundamentals, SEC filings
      charts/       # Lightweight Charts price/RSI/MACD panes, SVG time-series chart
      common/       # buttons, cards, fields, tabs, states, page headers
      layout/       # sidebar, top bar, app shell
      signals/      # signal badge, condition list, signal card, risk calculator
      tables/       # candles, indicators, watchlist, scanner, positions, trades, news, events
    contexts/       # API status provider (health + provider configuration)
    hooks/          # typed useApi hook with cancellation
    pages/          # dashboard, markets, stock/crypto analysis, portfolio, backtesting, settings
    services/       # centralised typed API layer
    types/          # backend response interfaces
    utils/          # formatting and navigation helpers
```

- All HTTP calls go through `src/services/api.ts`. `VITE_API_BASE_URL` is empty by default, so the browser calls `/api/...` on the same origin and Vite proxies it to `http://127.0.0.1:8000`. Set the variable only for a separately hosted build; that requires CORS on the FastAPI side.
- The frontend never calculates indicators, signals, risk or backtest metrics. It renders values returned by the backend and shows the backend's `detail` message when a request fails. There is no mock or fallback market data.
- Charts use Lightweight Charts for candlesticks, volume, RSI and MACD, plus a small SVG component for equity and drawdown curves. Indicator overlay values come from `/analysis`; RSI/MACD series come from the additive `/indicators` endpoint, which reuses the existing `compute_indicators` function.
- For production, run `npm run build` and serve `frontend/dist/` from any static host, reverse-proxying `/api` to FastAPI. `npm run preview` serves the built bundle on port 4173 with the same `/api` proxy for a quick local check.

### Data and execution semantics

- The first strategy is daily-only. Intraday indicators can be inspected from sources that provide completed intraday candles, but the daily strategy is not applied to those intervals.
- Binance's active, still-forming candle is excluded. Binance pagination fetches up to 20 pages / 20,000 candles; if that cap is reached, the API marks the history as truncated. Yahoo intraday and current-session candles are filtered conservatively; provider timestamps and market sessions can still vary.
- Session VWAP is only calculated when the input spacing is intraday. Daily OHLCV bars do not contain the intraday volume distribution, so daily session VWAP is returned as unavailable rather than approximated from typical price.
- The single-instrument backtest evaluates completed daily signals and uses next-bar open entries/exits for close-based conditions. Protective stops are checked against candle ranges and gaps are filled at the bar open when that is worse than the stop. Intrabar path, queue position, liquidity impact and exchange-auction mechanics remain approximate.
- Backtest costs are an aggregate configurable basis-point input, not a complete Indian broker/STT/GST/stamp-duty engine. Always run a broker-specific cost model before drawing conclusions.
- The app is not currently a validated investment system. Passing automated tests establishes code behaviour for tested fixtures, not trading edge or future performance.

---

## 1. Executive summary

Tradely should not be designed as a dashboard that turns a collection of indicators into an apparently precise BUY/SELL score. It should be a **strategy research and decision-support system** in which every strategy has its own entry rules, exit rules, position-sizing rules, execution assumptions and historical performance record.

The best-supported starting hypothesis is a combination of:

1. **Absolute momentum / time-series momentum** — is the instrument's own return positive?
2. **Relative strength momentum** — is it outperforming an appropriate benchmark or peer group?
3. **Trend regime filters** — is the longer-term trend supportive?
4. **Breakout or pullback triggers** — has an objective entry event actually occurred?
5. **Volatility-aware risk management** — how much can be bought while keeping planned loss within the risk budget?
6. **Strict out-of-sample validation** — does the approach continue to work after costs on unseen data?

The research does **not** identify a universally best indicator or a foolproof strategy. Academic work supports momentum as a phenomenon across asset classes and reports promising combined relative/absolute momentum results for Indian equities. Other research shows how technical-rule performance can be erased by transaction costs, false discoveries and overfitting. Tradely must preserve both sides of that evidence.

### Recommended initial research candidate

| Component | Initial specification | Role |
|---|---|---|
| Universe | Point-in-time NSE liquid-equity universe; begin with NIFTY 500 constituents if historical membership is available | Avoid illiquid names and survivorship bias |
| Absolute momentum | 6-month and 12-month returns, with the latest 1 month skipped for cross-sectional ranking | Identify persistent positive performance |
| Relative strength | Return relative to NIFTY 500 and sector benchmark | Prefer market/sector leaders |
| Trend filter | Close above rising SMA 200; SMA 50 above SMA 200 | Avoid many counter-trend entries |
| Entry trigger | Prior 20-day Donchian breakout, evaluated on a completed candle | Objective entry timing |
| Confirmation | Volume expansion; optional MACD/RSI context | Reduce weak breakout participation without indicator voting overload |
| Initial stop | Entry minus a configurable ATR multiple | Volatility-adjusted planned risk |
| Exit | ATR trailing stop or prior 10-day Donchian low; compare variants in testing | Let persistent trends continue while defining exit risk |
| Risk | Initially test 0.25%–0.50% account equity risk per trade | Limit loss from any one trade |
| Validation | Chronological walk-forward, untouched test period, realistic costs, multiple-testing controls | Detect overfit strategies |

This is a **candidate configuration to test**, not a proven profitable strategy and not a recommendation to trade it with real capital.

---

### 1.1 Owner-only deployment and non-goals

Tradely is being built for **one owner: the person running this private instance**. This is a hard product constraint, not merely the initial launch plan.

- No public signup, user invitations, multi-tenant accounts, customer dashboard, billing or public API.
- No public hosting or public-facing data service. Prefer a local installation bound to `127.0.0.1` / `localhost`.
- If remote access is genuinely needed later, use a private VPN/overlay network and strong authentication; do not expose the application or provider data endpoints openly to the internet.
- Keep API keys in backend environment variables or a local secrets file excluded from version control. Never put provider credentials in browser code or commit them to Git.
- Use read-only/public market-data credentials wherever possible. Tradely does not need broker trading permissions, withdrawal permissions or order-placement credentials.
- Store local research data, settings, watchlists and actual-holdings records on the owner's machine or private database. Backups should remain private and encrypted.
- Do not share, resell, republish or provide other people access to provider data, article content, derived feeds or the Tradely instance.
- Continue to obey each provider's personal-use terms, quota, attribution, retention and access restrictions. “Private” is not permission to bypass authentication, anti-bot controls, geographic restrictions or rate limits.
- Prefer manual links to official exchange filings where no permitted free data endpoint exists; do not scrape undocumented or restricted endpoints merely because the pages are visible in a browser.

**Deployment acceptance criterion:** a fresh installation runs for one owner, has no public account-registration flow, keeps credentials server-side, and is not reachable from the public internet by default.

## 2. What the research says

### 2.1 Time-series momentum across asset classes

Moskowitz, Ooi and Pedersen (2012), in *Time Series Momentum* (Journal of Financial Economics), documented return persistence over approximately one to twelve months across 58 liquid equity-index, currency, commodity and bond futures. They also reported partial reversal over longer horizons. This supports testing trend-following and absolute-momentum rules, but it does not prove that a particular EMA/RSI configuration will work on every NSE stock or intraday timeframe.

- Paper: [Time Series Momentum — Journal of Financial Economics](https://doi.org/10.1016/j.jfineco.2011.11.003)
- Open paper copy: [PDF](https://fairmodel.econ.yale.edu/ec439/mosk.pdf)

**Tradely implication:** include absolute momentum and trend-following as core research families. Do not overgeneralise the futures result to all individual shares, periods or transaction-cost conditions.

### 2.2 Relative, absolute and combined momentum in India

Sehgal, Pandey and Sen (published online 29 July 2024; issue publication in 2025) examined momentum strategies using NSE-listed shares. Their study designed six momentum strategies and compared raw and risk-adjusted results. The authors report that an enhanced strategy combining relative and absolute strength outperformed conventional price momentum in their Indian sample. They discuss investor overreaction as a possible explanation.

- Paper: [Relative, absolute or combined strength momentum strategies: what works for India?](https://doi.org/10.1108/IJOEM-09-2023-1518)
- Publisher page: [Emerald / International Journal of Emerging Markets](https://www.sciencedirect.com/science/article/pii/S1746880924000469)

**Tradely implication:** rank stocks using both their own trailing performance and their performance relative to a market/sector benchmark. Treat the paper as evidence for a research direction, not a guarantee that a specific lookback period, ranking formula or execution rule will be profitable in a new test period.

### 2.3 False discoveries and transaction costs in technical trading

Bajgrowicz and Scaillet, *Technical Trading Revisited: False Discoveries, Persistence Tests, and Transaction Costs*, studied technical trading rules on daily Dow Jones data from 1897 to 2011. They found that investors could not reliably select the future best-performing rules in advance and that low transaction costs could offset apparent in-sample performance. Their work is a direct warning against searching thousands of indicator combinations and reporting only the best historical result.

- Paper: [Technical Trading Revisited — PDF](https://www.scaillet.ch/pdfs/BajSca.pdf)
- Abstract: [University of Geneva / Olivier Scaillet](https://www.scaillet.ch/abstracts/Ab_BajSca.htm)

**Tradely implication:** maintain a complete experiment ledger, account for all costs, limit parameter mining and report failed experiments as well as successful ones.

### 2.4 Backtest overfitting and the Deflated Sharpe Ratio

Bailey, Borwein, López de Prado and Zhu (2017) proposed a framework for estimating the Probability of Backtest Overfitting (PBO), including combinatorially symmetric cross-validation (CSCV). They explain why a simple holdout can be unreliable when many strategies have been tried. Bailey and López de Prado (2014) introduced the Deflated Sharpe Ratio (DSR) to adjust for selection bias, multiple testing and non-normal returns.

- Paper: [The Probability of Backtest Overfitting](https://doi.org/10.21314/jcf.2016.322)
- Open research page: [eScholarship](https://escholarship.org/uc/item/4w1110bb)
- Paper: [The Deflated Sharpe Ratio](https://doi.org/10.3905/jpm.2014.40.5.094)

**Tradely implication:** keep the number of tried strategy variants, use walk-forward and genuinely untouched periods, and add PBO/DSR or other appropriate multiple-testing diagnostics before calling a strategy robust.

### 2.5 Technical rules in cryptocurrency markets

Hudson and Urquhart, *Technical Trading and Cryptocurrencies* (Annals of Operations Research; published online in 2019, volume published 2021), examined nearly 15,000 rules across five cryptocurrency markets. Their reported findings include significant predictability in their sample after multiple-hypothesis procedures, but they also report no Bitcoin predictability in the out-of-sample period they examined. The study is evidence that crypto technical rules merit testing; it is not evidence that a rule will work today, on every token or on a different exchange.

- Paper: [Technical Trading and Cryptocurrencies](https://doi.org/10.1007/s10479-019-03357-1)
- Publisher page: [Springer Nature](https://link.springer.com/article/10.1007/s10479-019-03357-1)

**Tradely implication:** reuse indicator mathematics where appropriate, but test crypto separately with exchange-specific volume, liquidity, fees, spread, 24/7 calendar and (if derivatives are ever added) funding costs.

### 2.6 Indian retail trading risk

SEBI's July 2024 study of individual intraday traders in the equity cash segment reported that 71% of the studied individuals were net loss-makers in FY23. Its calculation includes trading costs such as brokerage, exchange fees, SEBI fees, stamp duty, STT and GST.

- Source: [SEBI — Analysis of Intraday Trading by Individuals in Equity Cash Segment](https://www.sebi.gov.in/reports-and-statistics/research/jul-2024/study-analysis-of-intraday-trading-by-individuals-in-equity-cash-segment_84946.html)
- Report PDF: [SEBI study PDF](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf)

SEBI's August 2026 study of individual equity-derivatives traders reported that 87.7% were loss-makers in FY26. The report distinguishes derivatives from cash equities and notes that the reported P&L figures are squared-off gross P&L, not adjusted for transaction costs or open positions at year end. This statistic must not be represented as the loss rate for ordinary cash-equity swing traders.

- Source: [SEBI — Profitability of Individual Traders in the Equity Derivatives Segment (FY25–FY26)](https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html)
- Report PDF: [SEBI August 2026 report](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233506209.pdf)

**Tradely implication:** default to research, alerts, backtesting and signal observation. Make costs visible. Do not imply that indicator signals make trading safe or that a high win rate guarantees profit.

---

## 3. Strategy families to implement

Tradely should keep strategies separate. A stock can be in an uptrend but not yet have a valid entry; it can also be oversold in a persistent downtrend. Each strategy must emit its own state and explanation.

### 3.1 Strategy A — Combined absolute and relative momentum

**Purpose:** select instruments that are both performing positively and outperforming a benchmark or peer group.

Let `P_t` be the adjusted close at time `t` and `P_(t-k)` the adjusted close `k` trading sessions earlier.

Simple `k`-period return:

```text
R_k(t) = P_t / P_(t-k) - 1
```

Log return:

```text
r_k(t) = ln(P_t / P_(t-k))
```

A common cross-sectional momentum specification skips the most recent month to reduce short-term reversal effects:

```text
M_12_1 = P_(t-21) / P_(t-252) - 1
M_6_1  = P_(t-21) / P_(t-126) - 1
```

The exact trading-session counts are configurable. Do not assume 252 sessions for every instrument or use calendar-day offsets in place of trading-session offsets.

Relative momentum against benchmark `B`:

```text
RS_12_1 = M_12_1(stock) - M_12_1(benchmark)
RS_6_1  = M_6_1(stock)  - M_6_1(benchmark)
```

A multiplicative relative-strength ratio can also be used:

```text
RelativePrice_t = P_stock,t / P_benchmark,t
RelativeReturn_k = RelativePrice_t / RelativePrice_(t-k) - 1
```

Use either a clear excess-return definition or a relative-price definition consistently; do not mix them silently.

**Proposed weekly selection method:**

1. Build the eligible stock universe as it existed on each historical rebalance date.
2. Remove securities failing liquidity, price-history or data-quality rules.
3. Compute `M_6_1`, `M_12_1`, `RS_6_1` and `RS_12_1`.
4. Convert each metric to a cross-sectional percentile rank for that date.
5. Combine ranks using pre-registered weights, for example:

```text
MomentumRank = 0.25 * rank(M_6_1)
             + 0.25 * rank(M_12_1)
             + 0.25 * rank(RS_6_1)
             + 0.25 * rank(RS_12_1)
```

6. Require an absolute-momentum condition, such as both `M_6_1 > 0` and `M_12_1 > 0`, or test alternative filters.
7. Select a fixed number or top percentile of eligible securities, with a maximum sector exposure.
8. Rebalance at the pre-defined frequency (weekly or monthly). Include turnover and costs.

**Important:** rankings and thresholds are hypotheses. Test different lookbacks, weighting choices and rebalance frequencies on training data only, then lock them before final out-of-sample evaluation.

### 3.2 Strategy B — Trend-following with moving averages

**Purpose:** participate in established trends and avoid some counter-trend trades.

Proposed daily long setup for evaluation:

```text
Close[t] > SMA_200[t]
SMA_50[t] > SMA_200[t]
SMA_200[t] > SMA_200[t-20]
```

Optional momentum confirmation:

```text
RSI_14[t] > 50
MACD[t] > Signal[t]
```

Entry should still require a separate trigger, such as a Donchian breakout or a confirmed pullback. Do not buy solely because two moving averages have crossed; crossovers lag and can whipsaw in sideways markets.

**Exit variants to compare:**

- Close below prior 10-session low.
- Close below a configurable EMA/SMA trend level.
- ATR trailing stop.
- A combination where the first valid exit rule closes the position.

Compare the variants as separate experiments. Never select an exit after repeatedly inspecting the final test set.

### 3.3 Strategy C — Donchian channel breakout

**Purpose:** enter when price closes beyond a recent range high and exit when it breaks a trailing range low.

For lookback `n`:

```text
Upper_n[t] = max(High[t-n], ..., High[t-1])
Lower_n[t] = min(Low[t-n],  ..., Low[t-1])
```

The range deliberately ends at `t-1`. This prevents the current candle from moving the breakout threshold.

Candidate long entry:

```text
Close[t] > Upper_20[t]
AND Close[t] > SMA_200[t]
AND SMA_200[t] > SMA_200[t-20]
AND Volume[t] / AverageVolume_20[t-1] >= RVOL_MIN
```

Candidate exit:

```text
Close[t] < Lower_10[t]
OR Close[t] <= ActiveTrailingStop[t]
```

Test 20/10 and 55/20 channel pairs as independent variants. Do not assume that a classic parameter set is optimal for Indian cash equities after current costs.

### 3.4 Strategy D — Trend pullback continuation

**Purpose:** enter an established trend after a temporary retracement rather than buying an extended breakout.

Candidate long conditions:

```text
Close[t] > SMA_200[t]
SMA_50[t] > SMA_200[t]
SMA_200[t] > SMA_200[t-20]
Low[t] <= EMA_20[t] OR Low[t] <= EMA_50[t]
Close[t] > EMA_20[t]
RSI_14[t] crosses back above 50
```

The last two rules should use completed candles. A stop can be based on the recent swing low minus a volatility buffer or an ATR multiple. Define the swing-low algorithm explicitly (for example, a confirmed pivot with left/right bars); do not use a pivot before the right-side confirmation bars have elapsed.

This setup can fail when a pullback becomes a full reversal. The trend filter reduces, but does not eliminate, that risk.

### 3.5 Strategy E — Mean reversion (experimental)

**Purpose:** test whether unusually stretched prices revert towards a short-term mean during low-trend-strength regimes.

Bollinger Bands with period `n` and multiplier `k`:

```text
Middle[t] = SMA_n(Close)[t]
Std[t]    = rolling_std(Close, n)[t]
Upper[t]  = Middle[t] + k * Std[t]
Lower[t]  = Middle[t] - k * Std[t]
```

Candidate long setup for testing:

```text
ADX_14[t] < ADX_MAX
Close[t-1] < LowerBand[t-1]
Close[t] > LowerBand[t]
RSI_14[t] < RSI_MAX
```

Candidate exit: close at the middle band, at a pre-defined stop, or after a maximum holding period. Compare these exits independently.

**Do not use mean reversion blindly in strong trends.** An asset can remain oversold while falling. This strategy must have a regime filter and its own separate performance record.

### 3.6 Strategy F — Intraday opening-range breakout (experimental)

NSE's normal equity market session is 09:15–15:30 India time on trading days, subject to exchange holidays and special sessions. Tradely must obtain the current official calendar rather than hard-code every date.

Official source: [NSE market timings and holidays](https://www.nseindia.com/resources/exchange-communication-holidays).

A candidate 15-minute opening range:

```text
OR_High = max(High of 09:15–09:30 bars)
OR_Low  = min(Low of 09:15–09:30 bars)
```

Candidate long trigger after the range has completed:

```text
Close[t] > OR_High
AND Close[t] > VWAP[t]
AND RVOL[t] >= RVOL_MIN
```

Short-side trigger is the mirrored condition below `OR_Low` and VWAP, but short-selling availability, broker product type, intraday square-off and applicable exchange rules must be checked. Do not treat cash-equity intraday shorts as overnight short positions.

Test opening-range duration, entry buffer, time-of-day cutoff and exit rules as pre-registered parameters. Include spread, slippage, charges and missed fills. Intraday strategies should not be treated as ready for deployment because their charts look convincing.

---

## 4. Indicator reference: formulas and interpretation

All indicators must use the same canonical OHLCV series and the same warm-up policy. Tradely should document the implementation convention for every indicator; different libraries can differ in initialization and smoothing.

### 4.1 Simple Moving Average (SMA)

```text
SMA_n[t] = (1/n) * sum(Close[t-i], i=0..n-1)
```

Use as a smoothed trend reference. It is lagging and can generate repeated false crossovers in sideways markets.

### 4.2 Exponential Moving Average (EMA)

```text
alpha = 2 / (n + 1)
EMA_n[t] = alpha * Close[t] + (1-alpha) * EMA_n[t-1]
```

The first EMA value needs a documented seed, commonly the first `n`-period SMA. Do not compare results from different initialisation methods without noting the difference.

### 4.3 Relative Strength Index (RSI)

For close-to-close change:

```text
Change[t] = Close[t] - Close[t-1]
Gain[t]   = max(Change[t], 0)
Loss[t]   = max(-Change[t], 0)
```

Wilder smoothing for period `n`:

```text
AvgGain[t] = ((n-1)*AvgGain[t-1] + Gain[t]) / n
AvgLoss[t] = ((n-1)*AvgLoss[t-1] + Loss[t]) / n
RS[t]      = AvgGain[t] / AvgLoss[t]
RSI[t]     = 100 - 100/(1+RS[t])
```

If average loss is zero, handle the result according to a documented convention (normally RSI = 100); if both average gain and loss are zero, use a neutral/no-movement convention such as 50.

Common context levels are 30 and 70, but they are not automatic buy/sell thresholds. RSI can remain overbought in strong uptrends and oversold in strong downtrends.

### 4.4 MACD

```text
MACD[t]       = EMA_12[t] - EMA_26[t]
Signal[t]     = EMA_9(MACD)[t]
Histogram[t]  = MACD[t] - Signal[t]
```

A bullish crossover is a transition from `MACD <= Signal` to `MACD > Signal`; bearish is the reverse. Compute a crossover from completed values and record the crossover date once, rather than re-emitting it on every subsequent bar.

### 4.5 Average True Range (ATR)

```text
TR[t] = max(
    High[t] - Low[t],
    abs(High[t] - Close[t-1]),
    abs(Low[t] - Close[t-1])
)
```

Wilder ATR:

```text
ATR_n[first] = mean(first n True Range values)
ATR_n[t]    = ((n-1)*ATR_n[t-1] + TR[t]) / n
```

ATR measures absolute volatility, not trend direction. For comparing volatility across stocks with different prices, use normalized ATR:

```text
NATR[t] = 100 * ATR[t] / Close[t]
```

### 4.6 Average Directional Index (ADX)

Directional movement:

```text
UpMove   = High[t] - High[t-1]
DownMove = Low[t-1] - Low[t]

+DM[t] = UpMove   if UpMove > DownMove and UpMove > 0, else 0
-DM[t] = DownMove if DownMove > UpMove and DownMove > 0, else 0
```

Smooth `+DM`, `-DM` and `TR` using Wilder's method. Then:

```text
+DI = 100 * Smoothed(+DM) / Smoothed(TR)
-DI = 100 * Smoothed(-DM) / Smoothed(TR)
DX  = 100 * abs(+DI - -DI) / (+DI + -DI)
ADX = Wilder-smoothed DX
```

ADX estimates directional-trend strength, not direction. Use `+DI > -DI` or `-DI > +DI` to establish directional bias. Values around 20–25 are common heuristics, not universal statistically optimal cutoffs.

### 4.7 Bollinger Bands

```text
Middle[t] = SMA_n(Close)[t]
Upper[t]  = Middle[t] + k * rolling_std_n(Close)[t]
Lower[t]  = Middle[t] - k * rolling_std_n(Close)[t]
```

A common starting configuration is `n = 20`, `k = 2`. Specify whether the rolling standard deviation uses population (`ddof=0`) or sample (`ddof=1`) convention, because outputs differ slightly.

A touch of the upper or lower band is not a standalone reversal signal. In strong trends, price may walk along a band.

### 4.8 Donchian Channels

```text
DonchianHigh_n[t] = max(High[t-n : t])
DonchianLow_n[t]  = min(Low[t-n : t])
```

The interval notation excludes the current bar. This is essential for unbiased breakout detection.

### 4.9 Relative Volume (RVOL)

A basic daily version:

```text
RVOL[t] = Volume[t] / mean(Volume[t-20 : t-1])
```

For intraday use, compare the current time bucket with the same time-of-day bucket over prior sessions. Comparing 09:20 volume with a full-day average is not meaningful.

### 4.10 On-Balance Volume (OBV)

```text
OBV[t] = OBV[t-1] + Volume[t]   if Close[t] > Close[t-1]
OBV[t] = OBV[t-1] - Volume[t]   if Close[t] < Close[t-1]
OBV[t] = OBV[t-1]               otherwise
```

OBV is a cumulative price-direction/volume series. Its scale depends on the chosen starting point; compare its direction or normalized changes, not absolute levels across securities.

### 4.11 Volume Weighted Average Price (VWAP)

For intraday bars, with typical price:

```text
TypicalPrice = (High + Low + Close) / 3
VWAP[t] = sum(TypicalPrice[i] * Volume[i], i=session_start..t)
           / sum(Volume[i], i=session_start..t)
```

Reset VWAP at each trading-session boundary. VWAP should use the correct exchange session and reliable intraday volume.

### 4.12 Money Flow Index (MFI)

```text
TypicalPrice[t] = (High[t] + Low[t] + Close[t]) / 3
RawMoneyFlow[t] = TypicalPrice[t] * Volume[t]
```

Classify raw money flow as positive when typical price rises from the prior bar and negative when it falls. Over `n` bars:

```text
MoneyRatio = Sum(PositiveMoneyFlow) / Sum(NegativeMoneyFlow)
MFI = 100 - 100/(1 + MoneyRatio)
```

Handle zero negative flow safely. MFI is a price-and-volume oscillator, not direct evidence of institutional activity.

### 4.13 Chaikin Money Flow (CMF)

Money flow multiplier:

```text
MFM = ((Close - Low) - (High - Close)) / (High - Low)
MFV = MFM * Volume
CMF_n = sum(MFV over n bars) / sum(Volume over n bars)
```

When `High == Low`, assign a documented neutral multiplier (typically zero). CMF is bounded approximately between -1 and +1 when inputs are valid.

### 4.14 Stochastic RSI and CCI (optional)

Stochastic RSI:

```text
StochRSI = (RSI - rolling_min(RSI, n)) /
           (rolling_max(RSI, n) - rolling_min(RSI, n))
```

Use a defined zero-denominator policy. It is more sensitive than RSI and can produce many signals; do not add it merely to increase the apparent sophistication of the dashboard.

Commodity Channel Index:

```text
TP = (High + Low + Close) / 3
CCI = (TP - SMA_n(TP)) / (0.015 * MeanAbsoluteDeviation_n(TP))
```

CCI is another momentum/deviation oscillator. Treat it as optional and test its incremental value rather than assuming it adds independent information.

---

## 5. Signal semantics: condition, setup and trade trigger are different

Tradely should not display a single green badge merely because a stock's RSI or MACD is bullish.

Each symbol/strategy/timeframe should expose three distinct layers:

1. **Market condition:** bullish, bearish, range-bound, high-volatility or unavailable.
2. **Strategy setup:** the required environment exists, but no entry trigger has occurred yet.
3. **Actionable trigger:** the complete entry or exit rule has fired on a completed bar, subject to data freshness and tradability checks.

### Suggested signal states

| State | Meaning |
|---|---|
| `STRONG_BUY` | Strategy entry conditions met with stronger pre-defined confirmation; this is a rule label, not a guarantee |
| `BUY` | Strategy's complete long-entry trigger has fired |
| `WAIT` | Setup is forming but entry trigger is absent |
| `HOLD` | Existing position remains valid; no exit trigger |
| `EXIT` | Existing long position has met its exit rule |
| `AVOID` | Data, liquidity, market regime or risk gate blocks a new trade |
| `NO_SIGNAL` | No strategy condition currently applies |
| `STALE_DATA` | Latest required candle/data is too old or incomplete |

For Indian cash equities, a `SELL` signal should normally mean **exit an existing long position**. A short-entry signal must be a separate strategy and instrument mode with broker/exchange restrictions clearly indicated. Do not conflate cash-equity delivery selling with opening a short position.

### Weighted scores: use cautiously

A normalized score can help rank evidence, but it should not replace a strategy's hard entry and exit rules. Many indicators are transformations of the same OHLCV data and are highly correlated; counting EMA 20, EMA 50, EMA 200, MACD and price-vs-SMA as five independent votes overstates the evidence.

If a score is used, define component groups and normalise each component to `[-1, +1]`:

```text
Score = 100 * (w_trend*T + w_momentum*M + w_volume*V
               + w_volatility*H + w_price_action*P)
```

Where all weights are non-negative and sum to 1. Example research weights only:

```text
Trend          0.30
Momentum       0.25
Volume         0.20
Volatility     0.10
Price action   0.15
```

A score range such as `+60 to +100 = strong bullish`, `+25 to +59 = bullish`, `-24 to +24 = neutral`, `-25 to -59 = bearish`, and `-60 to -100 = strongly bearish` is only a UI convention until calibrated and validated. Never describe it as a probability of success unless it has been statistically calibrated on truly out-of-sample data.

**Preferred design:** expose strategy-specific outputs (e.g. `DONCHIAN_20: BUY`, `TREND_PULLBACK: WAIT`) and show the exact rules that passed or failed.

---

## 6. Risk management and position sizing

Risk management is mandatory. A signal engine without position sizing and loss controls is incomplete.

### 6.1 Risk budget

```text
RiskBudget = AccountEquity * RiskFraction
```

For a proposed initial test range, `RiskFraction` may be 0.0025–0.005 (0.25%–0.50%) of account equity per trade. These are conservative research settings, not personalised advice or a guarantee of safety.

### 6.2 ATR-based initial stop

For a long trade:

```text
InitialStop = EntryPrice - k * ATR
```

For a short trade:

```text
InitialStop = EntryPrice + k * ATR
```

A candidate `k = 2` can be tested. The correct multiplier depends on timeframe, instrument, volatility and execution model. Do not use the daily ATR as an intraday stop distance without explicitly converting timeframe and units.

### 6.3 Quantity calculation

For a long position:

```text
RiskPerShare = EntryPrice - StopPrice
RiskLimitedQty = floor(RiskBudget / RiskPerShare)
CapitalLimitedQty = floor(MaxPositionValue / EntryPrice)
FinalQty = min(RiskLimitedQty, CapitalLimitedQty, LiquidityLimitedQty)
```

Where:

```text
MaxPositionValue = AccountEquity * MaxPositionFraction
LiquidityLimitedQty = floor(ParticipationRate * ExpectedMarketVolume)
```

Use a conservative expected volume estimate and cap participation. If `RiskPerShare <= 0`, data is invalid, or the stop is not on the risk side of entry, reject the trade rather than forcing a quantity.

### 6.4 Example

Assume:

- Account equity: ₹100,000
- Risk fraction: 0.50%
- Entry: ₹1,000
- Stop: ₹980

```text
RiskBudget = 100,000 * 0.005 = ₹500
RiskPerShare = 1,000 - 980 = ₹20
Quantity = floor(500 / 20) = 25 shares
PlannedRisk = 25 * 20 = ₹500
PositionValue = 25 * 1,000 = ₹25,000
```

This excludes charges, spread, slippage, partial fills and gap risk. A stop order does not guarantee a fill at the stop price.

### 6.5 Trailing stop

For a long position, a simple ATR chandelier-style stop can be:

```text
TrailingStop[t] = HighestHighSinceEntry - k_trail * ATR[t]
ActiveStop[t] = max(ActiveStop[t-1], TrailingStop[t])
```

The `max` prevents a long-position stop from moving downward. Use completed-bar values to update the stop, and simulate fills using the next executable price or a conservative intrabar rule.

### 6.6 Portfolio-level controls to test

| Control | Candidate initial setting | Notes |
|---|---:|---|
| Risk per trade | 0.25%–0.50% of equity | Tune only using training/validation data |
| Maximum combined open planned risk | 2% of equity | Include correlation and gap risk separately |
| Maximum daily loss | 1.5% of starting day equity | Stop generating new intraday entries after breach |
| Maximum position value | Configurable, e.g. 10%–20% of equity | Do not assume every security is equally liquid |
| Maximum participation | Conservative configurable fraction of traded volume | Avoid unrealistic fills/market impact |
| Sector concentration | Configurable cap | Several stocks in one sector may be one correlated bet |
| Consecutive-loss pause | Optional, pre-registered rule | Must not be presented as a way to recover losses |

Do not add arbitrary rules until they are specified and tested. Include a gap-risk warning because overnight prices can jump beyond a stop.

---

## 7. Backtesting methodology: the proof standard

A backtest is a model of how a strategy might have behaved, not proof of future performance. Tradely must treat validation as a first-class feature.

### 7.1 Data integrity checks

Before any strategy run:

- Validate timestamps, timezone, exchange calendar and candle boundaries.
- Detect duplicate, missing, out-of-order and zero/negative OHLCV values.
- Enforce `High >= max(Open, Close, Low)` and `Low <= min(Open, Close, High)`.
- Detect suspicious zero-volume bars, stale quotes and price jumps.
- Keep source, retrieval time, adjustment status and revision metadata.
- Distinguish raw prices, split-adjusted prices and total-return/dividend-adjusted prices.
- Use adjusted prices consistently for long-horizon momentum calculations, but model actual executable prices and corporate-action cash flows correctly in trade simulation.
- Avoid mixing adjusted close with raw intraday open/high/low without a documented transformation.

### 7.2 Point-in-time universe and survivorship bias

Do not backtest today's NIFTY 500 constituent list as though it existed ten years ago. The universe must contain the securities that were actually eligible at each historical date, including securities subsequently removed, merged or delisted where data is available.

Using today's survivors in historical periods can overstate results. Store dated constituent snapshots or add/remove events, stable identifiers such as ISIN, symbol-change mappings, delisting events and corporate actions. If point-in-time membership is unavailable, label the backtest as **survivorship-biased / exploratory** and do not present it as a reliable historical performance claim.

Potential research references for understanding Indian constituent-history problems (third-party datasets; verify provenance before relying on them):

- [NSE historical index constituent reconstruction example](https://github.com/BKKB20/nse-index-history)
- [NIFTY 500 point-in-time data project](https://github.com/NegiShubh05/Nifty500_Pit_data)

These repositories are not official exchange feeds. Tradely should prefer licensed/official data and maintain its own provenance audit.

### 7.3 No look-ahead and no repainting

- If a signal uses a candle close, it becomes available only after that candle closes.
- For a signal computed at close `t`, assume execution no earlier than the next executable bar/open unless a realistic auction or order model is implemented.
- A breakout threshold for bar `t` must use data through `t-1`.
- Do not use future-confirmed swing highs/lows before their confirmation bars have elapsed.
- Do not calculate daily RSI/EMA using a still-forming daily candle and display it as final.
- Store the exact input timestamp and indicator values behind every alert.
- Re-run historical calculations after data revisions only with an audit trail; do not silently rewrite past signal records.

### 7.4 Execution model

At minimum, support:

1. **Next-bar execution:** signal after bar close; fill at next bar open plus adverse slippage.
2. **Spread-aware execution:** buy at ask / sell at bid where quote data exists.
3. **Market impact model:** increase slippage with order size relative to traded volume.
4. **Partial fills / no fills:** do not assume every order fills at the displayed close.
5. **Gap through stop:** if the next open is beyond the stop, fill at the next realistic available price, not at the more favourable stop price.
6. **Ambiguous OHLC bars:** if both stop and target are touched in a bar and tick data is unavailable, use a conservative adverse ordering or mark the trade ambiguous. Do not choose the favourable path.
7. **Liquidity limits:** reject/scale an order that exceeds the configured percentage of realistic bar volume.

### 7.5 Include all costs

For Indian equities, model at least:

- Brokerage (broker-specific; including any minimum/per-order charge)
- Exchange transaction charges
- SEBI turnover fee
- STT, with side/product-specific rules
- Stamp duty, with side/product-specific rules
- GST on applicable services/charges
- Depository/DP charges where applicable (especially delivery sale)
- Bid-ask spread
- Slippage and market impact
- Taxes on realised gains when the chosen report requires after-tax performance

Do not hard-code one permanent cost schedule. Keep a dated, broker-specific cost configuration and update it from official sources. Fees and tax rules can change. For each backtest, persist the exact cost schedule version and show both gross and net results.

For crypto spot, include exchange fee tier, spread, slippage, withdrawal/deposit costs if relevant to the tested workflow, and venue-specific liquidity. For crypto perpetuals/futures, include funding, liquidation mechanics, contract specifications and leverage; these products should be out of the initial Tradely scope.

### 7.6 Chronological train / validation / test

A simple recommended workflow:

- **Training:** earlier historical period for defining a small, pre-registered parameter grid.
- **Validation:** later chronological period for comparing candidates and detecting obvious instability.
- **Final test:** untouched latest period, opened once after the strategy specification is frozen.
- **Forward signal observation:** record live signals and subsequent market prices without creating simulated orders or positions. Compare observed outcomes with the strategy's pre-registered assumptions.

Do not repeatedly change a strategy based on its final-test performance and still call that period “out of sample.” After any strategy changes influenced by the test data, that period becomes development data and a new untouched test is needed.

### 7.7 Walk-forward testing

Use rolling or expanding chronological windows. For each fold:

1. Fit/choose parameters only on the training window.
2. Freeze parameters.
3. Evaluate on the next unseen window.
4. Roll forward and repeat.
5. Aggregate out-of-sample fold results.

If labels/positions overlap in time, use purging and an embargo around fold boundaries where required to prevent leakage. Maintain a clear separation of decision time and holding period.

### 7.8 Multiple testing and overfitting controls

- Record every strategy and parameter variant tested, including failures.
- Prefer economically motivated, small parameter grids over huge blind searches.
- Use False Discovery Rate methods when testing many hypotheses.
- Consider Probability of Backtest Overfitting (PBO) / CSCV as an additional diagnostic.
- Consider the Deflated Sharpe Ratio (DSR), which adjusts for selection bias and non-normal returns.
- Do not interpret a high Sharpe ratio from a large parameter search without the number of trials and selection procedure.
- Check performance across sectors, market-cap groups, volatility regimes, bull/bear/range periods and different start/end dates.
- Run parameter-stability tests: a robust strategy should not collapse when a parameter moves slightly.

### 7.9 Required performance metrics

Let `R_t` be periodic net portfolio return, `N` the number of periods per year, and `RF` the annual risk-free rate converted consistently to the same frequency.

**Net trade P&L**

```text
TradePnL = ExitCashFlow - EntryCashFlow - AllTradingCosts
```

For long quantity `Q`:

```text
GrossPnL = Q * (ExitPrice - EntryPrice)
NetPnL   = GrossPnL - EntryCosts - ExitCosts - OtherCosts
```

**Win rate**

```text
WinRate = NumberOfWinningClosedTrades / NumberOfClosedTrades
```

**Profit factor**

```text
ProfitFactor = Sum(PositiveNetTradePnL) / abs(Sum(NegativeNetTradePnL))
```

**Expectancy per trade**

```text
Expectancy = p_win * AvgWin - p_loss * AvgLoss - AvgCost
```

Use consistent sign conventions: `AvgLoss` can be represented as a positive magnitude in this formula.

**Average R-multiple**

```text
R_multiple = NetTradePnL / InitialPlannedRisk
```

**Annualised Sharpe ratio**

```text
Sharpe = sqrt(N) * mean(R_t - RF_period) / stdev(R_t - RF_period)
```

**Annualised Sortino ratio**

```text
Sortino = sqrt(N) * mean(R_t - RF_period) / downside_deviation(R_t, target)
```

Document the downside-deviation convention and target return. Sharpe/Sortino become unstable with short samples or low trade counts.

**Maximum drawdown**

```text
Peak_t = max(Equity_0, ..., Equity_t)
Drawdown_t = Equity_t / Peak_t - 1
MaxDrawdown = min(Drawdown_t)
```

**CAGR**

```text
CAGR = (EndingEquity / StartingEquity)^(1 / Years) - 1
```

**Calmar ratio**

```text
Calmar = CAGR / abs(MaxDrawdown)
```

**Turnover**

```text
Turnover = TotalTradedNotional / AveragePortfolioEquity
```

Also report number of trades, median holding period, exposure, average gross/net profit per trade, tail loss, drawdown duration, monthly returns, benchmark-relative return, capacity/liquidity and cost as a percentage of gross profits.

### 7.10 Minimum acceptance gate (proposed, not universal)

A strategy should not be marked `VALIDATED` merely because one backtest is profitable. Tradely may use a configurable review gate such as:

- Positive net expectancy after realistic costs in the untouched test period.
- Positive out-of-sample return and acceptable drawdown relative to pre-registered objectives.
- No dependence on one stock, one sector, one year or one exceptional trade.
- Performance survives reasonable increases in slippage and costs.
- Results remain directionally similar across nearby parameter values.
- Adequate trade count and confidence intervals; avoid declaring success from a tiny sample.
- Acceptable performance across different market regimes.
- PBO/DSR or equivalent selection-bias review where the number of experiments warrants it.
- Forward-observed signal behaviour does not materially contradict historical assumptions; any discrepancy is investigated before a strategy is labelled stable.

Thresholds must be specified before the final test is opened. A strategy that fails the gate should remain `RESEARCH_ONLY`, not be promoted to the live signal engine.

---

## 8. Market regime classification

Tradely should classify market conditions separately from trade signals. This prevents a strategy from treating every environment as suitable.

Candidate features:

- Long-term trend: close vs SMA 200; SMA 200 slope.
- Trend strength: ADX and directional indicators.
- Realised volatility: rolling standard deviation of returns.
- Volatility level: ATR / close or NATR.
- Benchmark breadth: proportion of eligible constituents above their own SMA 50/SMA 200.
- Market drawdown: benchmark distance from trailing peak.

A first rule-based regime label could be:

| Regime | Candidate condition | Strategy preference to test |
|---|---|---|
| Bull trend | Benchmark above rising SMA 200; ADX/DI supportive | Momentum, breakout, pullback |
| Bear trend | Benchmark below falling SMA 200 | Avoid new long entries; study defensive rules separately |
| Range / low trend | Low ADX; limited moving-average slope | Mean reversion research only |
| High volatility | NATR/realised volatility above historical percentile | Reduce position size or block entries |
| Data/market stress | Stale data, circuit/illiquidity, abnormal spread | `AVOID` |

These are candidate labels. Test the thresholds and regime transitions. Do not force a strategy to trade when no valid opportunity exists.

---

## 9. Multi-market design: Indian equities, international equities and crypto

Tradely must support three asset classes through separate data adapters. The indicator and strategy mathematics can be shared where the underlying data semantics are compatible, but symbols, sessions, currencies, corporate actions, volume definitions, fees and execution assumptions must remain market-specific.

> **Terminology:** cryptocurrencies are digital assets/tokens, not stocks. They appear in the same analyzer experience but must be identified as `crypto` instruments, not equities.

### 9.1 Indian listed equities — NSE and BSE

- Store exchange + trading symbol + ISIN (where available) as the security identity. A company may have listings on both NSE and BSE; do not merge their candles or volumes.
- Use the official Indian exchange calendar, including holidays and special sessions. Normal NSE cash-equity hours are 09:15–15:30 Asia/Kolkata on trading days, subject to official notices.
- Account for splits, bonuses, rights issues, dividends, symbol changes, mergers and delistings in historical price series.
- Preserve a point-in-time security universe for research. Do not backtest only today's surviving constituents.
- Distinguish EOD, delayed and intraday feeds in every chart, scan result and signal.
- Treat official NSE/BSE filings as the authoritative source for listed-company disclosures where a permitted, reliable access route exists.

### 9.2 International listed equities

- Launch with US listings (NYSE/Nasdaq) as the first international market because free data availability and public company filings are comparatively accessible. Add other countries only after confirming symbol coverage, exchange calendars, currency handling, corporate-action data and data rights.
- Store exchange, MIC (where available), native symbol, currency, timezone, country and a stable instrument identifier.
- Do not treat an ADR, ordinary share and secondary listing as the same instrument without explicit mapping.
- Convert reporting currency only for portfolio-level aggregation; preserve native-currency returns for the underlying strategy.
- Use exchange-specific calendars and daylight-saving-aware session handling.
- For US company filings, SEC EDGAR provides free access to filings and JSON APIs for submissions/XBRL data. EDGAR is not a quote feed and does not itself provide a universal future earnings calendar.
- For non-US companies, use the relevant national regulator, exchange disclosure service or issuer investor-relations page. There is no single free global corporate-filings API covering every exchange.

### 9.3 Cryptocurrency spot assets

- Crypto trades 24/7. Store all candle boundaries in UTC and convert only for display.
- Identify assets by canonical provider asset ID and chain/contract address where relevant; ticker symbols alone are not unique.
- Store exchange venue and market pair for exchange-specific candles, e.g. `BTCUSDT` on Binance. Do not combine Binance, Coinbase and other venues into one candle series without an explicit consolidation methodology.
- Distinguish exchange-native volume from aggregate volume. They are not interchangeable.
- Filter assets by liquidity, age, spread and data quality. Newly listed or thinly traded tokens must not receive the same confidence as liquid assets.
- The initial scope is spot crypto analysis. Perpetual futures and leveraged derivatives require separate funding, liquidation, contract and leverage models and are not part of the initial release.

### 9.4 Shared instrument and data model

Every instrument should have `asset_class` (`equity` or `crypto`), `market`, `exchange_or_venue`, `native_symbol`, `display_symbol`, `currency`, `timezone`, `country` (nullable), `ISIN` (nullable), `provider_asset_id` (nullable), `contract_address` (nullable), and effective-dated symbol aliases. Every market-data record must retain its original provider and venue.

---

## 10. Free and low-cost data-provider strategy

Provider pricing, free quotas, terms and geographic availability can change. Re-check official pages before implementation and periodically while using the app. **Free to call does not mean unrestricted use, unlimited storage or permission to redistribute.** Tradely is owner-only, so public/commercial redistribution is out of scope; personal-use restrictions, rate limits, attribution, retention rules and exchange requirements still apply. Keep all provider integrations behind adapters and keep credentials on the backend.

### 10.1 Practical provider summary

| Asset / feature | No-cost or free-tier option | What it is useful for | Important limitation |
|---|---|---|---|
| Indian equities EOD | Yahoo Finance through `yfinance`; TejHQ free-key tier for private use | Prototype historical bars, quotes/reference data and indicators | Yahoo data is unofficial and intended for personal use; TejHQ free terms are private/personal, not a free public-product licence; not a guaranteed licensed live feed |
| International equities EOD | Yahoo Finance through `yfinance`; Alpha Vantage free tier; selected Twelve Data Basic symbols | US-first and other provider-covered global shares | Yahoo is personal-use only; Alpha Vantage free quota is 25 requests/day for most free datasets; Twelve Data Basic covers a limited set of markets and request credits |
| US company filings | SEC EDGAR | Official filings, submissions and XBRL company facts | US issuer filings only; not an equity quote feed or complete forward corporate-events calendar |
| Crypto exchange data | Binance public Spot REST/WebSocket market-data endpoints | Exchange-specific OHLCV, trades, ticker and order-book data | Venue-specific; endpoint weights, geographic availability and exchange terms apply |
| Aggregate crypto data | CoinGecko Demo API | Asset discovery, market caps, aggregated prices and broad historical context | 10,000 call credits/month, 100 calls/minute, attribution required; Demo plan is limited and not a commercial redistribution licence |
| Global/company news discovery | GDELT DOC API and GDELT datasets | Search news mentioning companies, sectors, countries and macro topics | Broad discovery/indexing, not an authoritative financial-news or issuer-disclosure service; article content remains subject to publisher rights |
| Company news by ticker | Yahoo Finance news through `yfinance` for private/personal research; provider adapters such as Finnhub only after checking plan coverage | Convenient ticker-oriented article discovery | Yahoo personal-use restriction; coverage and free-plan rights vary by provider and ticker/exchange |
| News publisher feeds | Publisher-provided RSS feeds | Headline, source, date and original article link | Per-publisher feed availability and terms apply; do not republish full articles without permission |
| Development-only news API | NewsAPI Developer plan | Test a news-feed UI during development | 100 requests/day, 24-hour delay; developer plan is for development/testing only, not staging or production |

### 10.2 Yahoo Finance through `yfinance` — broad prototype source

- Project: [yfinance documentation](https://ranaroussi.github.io/yfinance/) · [GitHub](https://github.com/ranaroussi/yfinance)
- The library exposes historical prices, quote metadata, financial statements, corporate-action fields, calendars and news/search functions for symbols supported by Yahoo Finance.
- Indian symbols commonly use `.NS` (NSE) and `.BO` (BSE) suffixes; US tickers commonly use their exchange ticker. Other international suffixes vary and must be resolved from provider search/metadata.
- It is a community-maintained library that calls Yahoo's publicly available interfaces. It is **not an official Yahoo Finance API**, is not endorsed by Yahoo, and the project documentation says Yahoo Finance data is intended for **personal use only**.
- There is no contractual uptime, stable public API SLA or guaranteed rate limit. Requests can be throttled, changed or temporarily fail. Do not build a high-frequency/live signal system on top of it.
- Use it only for the owner's local/private personal research after checking Yahoo's current Terms of Service. Do not assume that an open-source library licence grants rights to the underlying market data. Tradely must not redistribute or expose this data to other users.
- Classify data freshness from the actual returned timestamp/market status. Never label a Yahoo quote as real-time unless the provider explicitly confirms that for that instrument and entitlement.

**Recommendation:** `yfinance` is the easiest broad-market starting adapter for the owner's private Tradely prototype, but it must be replaceable when a source becomes unavailable or its terms change. It is not an official Yahoo API and must not be used to redistribute Yahoo data.

### 10.3 India EOD data — TejHQ (private-use tier)

- Docs: [TejHQ API documentation](https://tejhq.dev/docs)
- Free key: [TejHQ API key](https://tejhq.dev/keys)
- Data terms: [What you can do with TejHQ data](https://tejhq.dev/data-terms)

The documented service provides Indian-equity EOD data and selected reference/corporate-action endpoints. Its published free-key quota has been listed as 1,000 calls/day and 300 calls/minute; confirm the current dashboard/terms when creating a key.

**Limitations:**

- EOD data is not an intraday feed.
- TejHQ's terms state that its free access is for personal research/private dashboards within limits. Use in a product, for clients or inside a business may require a paid plan.
- TejHQ states it does not hold an NSE/BSE licence that it can pass through to users. Exchange data rights apply independently; its software/code licence does not license market data.
- Do not redistribute raw exchange data unless the applicable rights explicitly permit it.

Use TejHQ as an optional private EOD adapter and cross-check it against another source. Do not make the entire application dependent on it.

### 10.4 Official Indian exchange data — licensing boundary

- NSE data policy: [NSE Data Sharing & Usage Policy](https://www.nseindia.com/static/market-data/nse-data-policy)
- NSE corporate data: [Paid Corporate Data](https://www.nseindia.com/static/market-data/corporate-data-subscription)
- BSE data access: [BSE Self Data Feed](https://marketdata.bseindia.com/)
- BSE product pricing reference: [BSE Information Products Pricing Sheet](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)

Official exchange pages are the preferred source for authoritative Indian announcements and licensed market data. However, NSE explicitly describes data usage/sharing rules and paid subscriptions for commercial market-data access; BSE's data-feed service uses registration, KYC, plan selection and commercial terms. Therefore, do **not** assume that a publicly viewable exchange page or an undocumented JSON endpoint is a free API that Tradely may scrape, store or redistribute.

For the owner-only private build, link directly to official filings and use only permitted data sources. Do not bypass anti-bot controls, authentication, rate limits or exchange terms. Tradely will not serve exchange data to other users.

### 10.5 International equities — Alpha Vantage and Twelve Data as constrained fallbacks

**Alpha Vantage**

- Docs: [Alpha Vantage API documentation](https://www.alphavantage.co/documentation/)
- Free limits: [Alpha Vantage support](https://www.alphavantage.co/support/)
- Its support page currently states 25 API requests/day for most free datasets. It covers multiple asset classes and global symbols, but each endpoint, symbol and entitlement must be checked.
- Realtime and 15-minute delayed US stock market data are identified as premium-only. Do not assume the free plan provides live US quotes.
- Alpha Vantage's news/sentiment and some calendar/intelligence functions may require paid access; confirm endpoint entitlement in the account before depending on them.

**Twelve Data**

- Pricing: [Twelve Data plans](https://twelvedata.com/pricing)
- Docs: [Twelve Data documentation](https://twelvedata.com/docs)
- Its Basic plan currently lists 8 API credits/minute and 800/day, with limited trial WebSocket credits and access to a limited number of markets. The pricing page lists real-time US equities, forex and crypto on Basic; global EOD equity coverage is shown on a paid tier.
- Endpoint weights consume different credits. Check exact symbol/exchange support before relying on it for a market.

These are optional adapters and quota-limited fallbacks, not a guarantee of free unrestricted global stock coverage. Do not hard-code any assumption that all country/exchange symbols are supported.

### 10.6 US company filings — SEC EDGAR

- Official guide: [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data)
- SEC APIs: [data.sec.gov](https://www.sec.gov/edgar/sec-api-documentation)
- The SEC provides free access to filings and JSON data for company submissions and XBRL company facts. The SEC currently states a maximum rate of 10 requests/second and requires a declared descriptive `User-Agent` header.
- EDGAR is the authoritative source for US filings such as 10-K, 10-Q, 8-K and relevant ownership disclosures. It is not a general real-time quote API and does not guarantee a structured future earnings date for every issuer.
- Keep requests efficient, cache within permitted rules, respect SEC fair-access guidance and link to the original filing.

### 10.7 Crypto — Binance public market data

- Official docs: [Binance Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api)
- Market-data-only endpoints: [Binance market data only](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md)
- Binance documents public market-data endpoints with security type `NONE`; the market-data-only REST/WebSocket hosts do not require an API key for those endpoints.
- Useful endpoints include exchange information, klines/candles, ticker price, 24-hour ticker, recent trades and order-book depth.
- Example public host: `https://data-api.binance.vision`; public WebSocket market data host: `wss://data-stream.binance.vision`.
- This is Binance venue data, not a consolidated global crypto price. Store venue/pair and respect request weights, rate limits, geographic access and Binance terms.
- Tradely does not need an API key for public market-data-only endpoints. Never request or store account/trading permissions for this project.

### 10.8 Crypto — CoinGecko Demo as an aggregate fallback

- Pricing: [CoinGecko API pricing](https://www.coingecko.com/en/api/pricing)
- Docs: [CoinGecko API docs](https://docs.coingecko.com/)
- The current Demo plan lists 10,000 call credits/month and 100 calls/minute, with attribution required and data freshness from 60 seconds. The free Demo plan is for limited testing/exploration; commercial licensing is listed on paid tiers.
- Use it for asset discovery, metadata, market-cap/volume context and aggregate price reference. Check endpoint history depth and credit weights.
- Do not present aggregate data as an exchange-executable quote. Do not assume that Demo permits commercial redistribution.

### 10.9 News and company-event providers — global, stock-specific, no AI

Tradely's news and event information must appear **inside the analysis page for the selected instrument**. Do not build a standalone news calendar, calendar grid or global events page. Support company-specific feeds for Indian and international equities, plus asset/project-specific news for crypto.

**A. GDELT — first global news-discovery source**

- Project: [GDELT](https://www.gdeltproject.org/)
- Data/query guide: [GDELT data and querying](https://www.gdeltproject.org/data.html)
- DOC API: [GDELT DOC 2.0 API](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
- GDELT describes its underlying database as free and open. It can discover global coverage matching a company name, ticker-related keyword, industry, country, regulator or macro topic.
- GDELT is a discovery/indexing source, not an authoritative issuer disclosure provider and not a guarantee of complete coverage. Matching must handle company aliases and ambiguous names.
- Store headline/metadata and the original publisher URL. Do not copy or republish publisher article text or images unless permitted by the publisher's rights. The fact that GDELT is open does not make third-party article content public domain.

**B. Official issuer and regulator sources**

- India: NSE/BSE company announcements and filings, plus the listed company's investor-relations site. Verify permitted access and exchange data licences; official exchange market-data feeds are not automatically free.
- United States: SEC EDGAR filings, issuer investor-relations news releases and the relevant exchange's official notices.
- Other international markets: use the relevant national securities regulator/exchange disclosure page and the issuer's investor-relations/press-release feed. There is no single verified, free, universal API for every country's official corporate events.
- Crypto: official exchange announcement pages and project/foundation blogs or RSS feeds. Match announcements to the correct asset, chain and contract; do not infer that an exchange listing notice applies to every token with a similar ticker.

**C. Publisher RSS feeds**

Use publisher-provided RSS/Atom feeds where available and permitted. A feed can provide the headline, canonical link, timestamp and sometimes a short description. Examples of publishers to evaluate include Reuters, CNBC, CNBC-TV18, Economic Times, Business Standard, Mint and other regional financial publishers. Feed availability and reuse rights vary by publisher. Do not assume a publisher permits full-text republication or unrestricted commercial use.

**D. NewsAPI — development/testing only**

- Pricing: [NewsAPI pricing](https://newsapi.org/pricing)
- The Developer plan currently lists 100 requests/day and a 24-hour article delay, and its terms limit it to development and testing; it cannot be used in staging or production. Use it to prototype the news UI only, not as Tradely's production news provider.

**E. Yahoo Finance news through `yfinance` — private prototype only**

`yfinance` exposes news/search functions alongside market data. It inherits the same critical Yahoo Finance restriction: the project documentation says the underlying data is intended for personal use only and the library is unofficial. Use only for a private local prototype after checking Yahoo's terms; do not treat it as a public commercial news API.

**F. Finnhub and other ticker-news API providers — optional, entitlement-gated**

Finnhub documents company-news and market-news APIs, but Tradely must verify the chosen plan supports each required endpoint and the specific country/ticker, and obtain confirmation of caching/display/redistribution rights. Do not mark a provider as a free production dependency solely because it offers a free API key. Keep Finnhub disabled until these checks pass.

#### Stock/instrument-page news and event presentation

When a user opens a selected instrument, show a contextual panel:

1. **Overview** — latest company/asset-specific headlines, relevant sector/industry/global market coverage and important official notices, each clearly labelled by relevance.
2. **Company / project news** — issuer, company, project or protocol-specific news.
3. **Official filings / announcements** — exchange, regulator, issuer or crypto-exchange announcements with the original source link.
4. **Upcoming company events** — only dated events belonging to the currently selected equity (earnings/results, board meeting, dividend, split, AGM/EGM, investor meeting, etc.), as compact rows/cards rather than a calendar grid.
5. **Past announcements** — prior event disclosures useful for understanding price/volume reaction.

For Indian equities, use Asia/Kolkata for display. For international equities, use the instrument's exchange timezone and optionally show the viewer's local time. Store all timestamps internally in UTC. Distinguish `published_at`, `announced_at`, `scheduled_for`, `retrieved_at` and `last_verified_at`.

For crypto assets, display news/announcements related to the exact asset/project, relevant chain upgrades, exchange listings/delistings, token unlock information only when a source provides a verifiable schedule, and security/governance notices. Do not create a universal crypto calendar for the initial release.

#### News matching, deduplication and classification

- Match equities by exchange + symbol and ISIN where available; retain company aliases and historical symbols. Match crypto by canonical asset ID, chain and contract address where applicable.
- Do not match only on a common company or token name.
- De-duplicate by canonical URL, normalized title, publisher and publication time, but preserve separate official filings.
- Classify items as `instrument_specific`, `sector_relevant`, `market_wide`, `regulatory`, `official_filing` or `crypto_project_specific`.
- Preserve source name, source URL, publisher, publication time, retrieval time and freshness state.
- Do not use news sentiment, headline tone or article volume to generate a BUY/SELL signal. News is contextual information; all trade signals remain deterministic and indicator/strategy-based.

#### Minimum news/event data model

`news_articles`: `id`, `headline`, `snippet` (only where permitted), `publisher`, `canonical_url`, `published_at_utc`, `retrieved_at_utc`, `source_id`, `category`, `relevance_type`, `asset_class` and deduplication fingerprint.

`instrument_news_links`: `article_id`, `instrument_id`, `market`, `exchange_or_venue`, `symbol`, `ISIN` (nullable), `provider_asset_id` (nullable), `match_method` and `match_confidence` (only if a deterministic matching score is implemented).

`instrument_events`: `id`, `instrument_id`, `market`, `exchange_or_venue`, `event_type`, `title`, `description`, `announced_at_utc`, `scheduled_at_utc` (nullable), `date_precision`, `status`, `source_name`, `source_url`, `retrieved_at_utc` and `last_verified_at_utc`.

Recommended backend routes:

```text
GET /api/instruments/{instrument_id}/news
GET /api/instruments/{instrument_id}/events?status=upcoming
GET /api/instruments/{instrument_id}/announcements
GET /api/instruments/{instrument_id}/intelligence
GET /api/markets/providers/status
```

Paginate feeds, cache only within provider terms and show a visible source/freshness badge. If no verified event exists, show `No verified upcoming events found` rather than infer a date.

### 10.10 Recommended zero-subscription configuration for a private Tradely build

For the first version running locally for one person, use the following practical combination and make every provider replaceable:

| Need | First choice | Fallback / enrichment | Display policy |
|---|---|---|---|
| Indian equity historical/EOD prices | TejHQ keyless/free-key endpoints, subject to its personal-use terms | Yahoo Finance via `yfinance` (`.NS` / `.BO`) | Label EOD; compare sources; do not redistribute raw data |
| International equity historical prices | Yahoo Finance via `yfinance` for covered tickers | Alpha Vantage (25/day) or Twelve Data Basic for supported symbols | Label source and delay; no promise of full global coverage |
| US issuer disclosures | SEC EDGAR | Issuer investor-relations releases | Link original filings; honour SEC fair-access rules |
| Crypto exchange candles | Binance public Spot market-data endpoints | CoinGecko Demo for aggregate context | Label the Binance market pair or CoinGecko aggregate separately |
| Company/global news | GDELT discovery + publisher RSS feeds that permit use | Yahoo Finance news via `yfinance` only for private/personal use | Store headline/metadata/link; do not republish article text |
| Indian company events | Official NSE/BSE filing pages and issuer IR sources, through permitted access | Provider adapter only after confirming exchange rights | Show source-backed event rows on the relevant stock page |
| International company events | SEC filings for US names + issuer IR/regulator/exchange sources for other markets | Finnhub/other calendar API only after plan and rights verification | Never infer unannounced dates; show `not available` where no source exists |
| Crypto project/exchange news | Official project and exchange announcement feeds + GDELT | A crypto-news API only after confirming its free-tier endpoint access and reuse terms | Match by canonical asset/chain, not ticker string alone |

**Practical implementation order:**

1. Implement the `yfinance` adapter for quick cross-market equity search/history in a private local development environment.
2. Add TejHQ for better Indian EOD history and adjusted-price/symbol information, while respecting the personal-use boundary.
3. Add Binance public Spot REST/WebSocket candles for crypto. No trading-enabled API key is needed for the documented public market-data-only endpoints.
4. Add CoinGecko Demo only for aggregate crypto metadata/market context; cache responsibly within its plan and show attribution.
5. Add GDELT + permitted publisher RSS as the default general-news discovery layer, then SEC EDGAR and official issuer/exchange disclosures for event/filing verification.
6. Add Alpha Vantage or Twelve Data only for symbols/endpoints that are missing from the primary providers and only while within the free quotas.

This setup can be implemented without a recurring API subscription for private experimentation, but it is not a guarantee of institutional-quality live data, universal symbol coverage, or rights to publish data to other users. Do not make a free-tier provider a hard dependency: display provider health and freshness, allow a source to be disabled, and fail closed when data is stale or unavailable.

### 10.11 Provider-adapter architecture

```text
MarketDataProvider
  ├── YahooFinancePersonalProvider   (yfinance; private prototype only)
  ├── IndiaEodProvider               (TejHQ; private-use tier)
  ├── AlphaVantageProvider           (quota-limited fallback)
  ├── TwelveDataProvider              (limited free-tier coverage)
  ├── SecEdgarProvider                (US filings/fundamentals, not price feed)
  ├── BinanceSpotProvider             (public crypto venue data)
  └── CoinGeckoAggregateProvider      (aggregate crypto data)

NewsProvider
  ├── GdeltNewsProvider               (global discovery)
  ├── PublisherRssProvider            (publisher feeds subject to terms)
  ├── IssuerDisclosureProvider        (exchange/regulator/IR sources)
  ├── SecEdgarFilingsProvider         (US issuer filings)
  ├── YahooNewsPersonalProvider       (private prototype only)
  └── FinnhubNewsProvider             (disabled until plan/rights verified)
```

If a provider is unavailable, the application must show that data source as unavailable/stale and fall back only to an explicitly configured alternative. Never silently blend sources with different adjustments, timezones, currencies or candle definitions.

---

## 11. Tradely application modules

Recommended navigation:

1. **Market Overview** — Indian indices, selected international indices, market breadth, sector performance, crypto market overview and data freshness.
2. **Market Scanner** — symbols grouped by strategy state; clearly identify real-time, delayed or EOD data and the source market.
3. **Stock Analyzer** — Indian and international equities: charts, fundamentals where available, indicator values, strategy setups, levels and exact rule explanations.
4. **Crypto Analyzer** — crypto spot assets with exchange-specific charts, venue/aggregate market metadata, liquidity and volatility context.
5. **Strategy Lab** — configure strategies, run historical backtests, compare variants and preserve experiment history. Backtesting is an offline research simulation, not a user-facing paper-trading account.
6. **Watchlists & Alerts** — user-defined instruments and deterministic indicator/price-trigger notifications across all supported markets.
7. **Portfolio Tracker** — track the user's actual holdings using manually entered transactions or an imported CSV; calculate cost basis, current value, realised/unrealised P&L and currency exposure. Do not create simulated holdings or pretend fills.
8. **Trade Journal** — record trades the user actually made, their rationale and post-trade outcome; keep this separate from generated signals and backtest results.
9. **Risk Dashboard** — portfolio concentration, currency exposure, position sizing estimates, correlated exposure and drawdown analytics based on user-provided actual holdings.
10. **Settings** — data sources, provider quotas, costs, indicator periods, strategies, timeframes, alerts and display preferences.

There is **no standalone Events Calendar page**. Company news, official filings and upcoming/past corporate events appear inside the analysis page for the relevant Indian or international stock. Crypto project and exchange news appear inside the corresponding crypto asset page. All event items are stock/asset-specific compact rows or cards, not calendar grids.

### Required instrument-analysis screen

Every instrument analysis page should show:

- Market, asset class, exchange/venue, symbol, ISIN/asset ID, quote currency and data provider.
- Latest price, percentage change, timestamp and freshness state.
- Candlestick chart with selectable intervals supported by that provider.
- Volume, EMA/SMA overlays and selectable oscillators.
- Numeric indicator table with formula/period and interpretation.
- Market-regime classification.
- Separate outputs for each strategy.
- Passed/failed rule checklist with current values and thresholds.
- Entry reference, stop reference, target levels (if applicable), quantity estimate and risk/reward calculation.
- Backtest summary for the exact strategy version and universe.
- Previous signal history, including invalidated or withdrawn signals.
- **News & Events panel:** company-specific articles, relevant sector/market coverage, official filings and upcoming/past corporate events for equities; asset/project-specific and exchange announcements for crypto.
- Original source, publisher, publication timestamp, announcement timestamp, scheduled event date, retrieval time and freshness state for every news/event item.
- Clear distinction between official company disclosures, third-party news, sector context and market-wide stories.

Every signal must be reproducible from stored inputs and the strategy version that generated it. News and corporate events provide context and must not independently generate or override a BUY/SELL signal. Tradely does not place orders and does not offer paper trading in this scope.

---

## 12. Technical architecture (no AI)

A suitable first implementation:

| Layer | Suggested technology | Responsibility |
|---|---|---|
| Frontend | React + TypeScript | Dashboard, charts, scanners, controls |
| UI styling | Tailwind CSS | Responsive design and themes |
| Charting | Lightweight Charts or equivalent | Candles, volume and overlays |
| Backend | Python + FastAPI | API, data validation and strategy services |
| Data processing | pandas + NumPy | Time series and numerical calculations |
| Indicators | Transparent in-house implementations or a verified indicator library | Reproducible indicator values |
| Database | PostgreSQL | Users, watchlists, signals, experiments, actual holdings and user-entered trade journal |
| Time-series storage | PostgreSQL/TimescaleDB or Parquet files | Historical candles and research datasets |
| Cache | Redis (optional initially) | Rate limits, provider cache and scanner snapshots |
| Background jobs | APScheduler/Celery or a simple worker | EOD refresh, indicator computation and scans |
| Testing | pytest + deterministic fixtures | Formula, signal and execution correctness |

No language model, AI inference service, ML prediction model or AI-generated score is part of the design. All outputs must be traceable to deterministic code, numerical inputs and explicit rules.

### Suggested backend service boundaries

```text
tradely/
  backend/
    app/
      api/                 # FastAPI routes
      providers/           # India/global/crypto market-data, filings, news and RSS adapters
      market_data/         # Normalisation, trading sessions, corporate actions
      news/                # Fetching, normalization, ticker matching, deduplication
      instrument_events/   # Stock/project-specific events and source/status verification
      indicators/          # SMA, EMA, RSI, MACD, ATR, ADX, etc.
      strategies/          # Momentum, Donchian, Pullback, Mean Reversion, ORB
      signals/             # State machine, explanation and persistence
      risk/                # Position sizing, stops, exposure limits
      backtesting/         # Execution model, portfolio simulator and metrics
      research/            # Walk-forward, PBO/DSR and experiment registry
      storage/             # Database and Parquet repositories
      tests/
  frontend/
    src/
      pages/
      components/
      charts/
      features/
  research/
    strategy_specs/
    experiment_logs/
    reports/
  data/                    # Local/private research data only where licensed
```

---

## 13. Engineering rules and acceptance tests

These rules are not optional polish; they protect the correctness of every signal.

### 13.1 Indicator correctness

- Unit-test every formula against hand-calculated fixtures and at least one independently checked reference implementation.
- Specify warm-up lengths, smoothing and zero-denominator behaviour.
- Ensure no future rows are read by rolling windows.
- Test missing bars and corporate-action boundaries.
- Assert finite values where values are mathematically defined.
- Confirm identical output for batch and incremental calculations within the documented tolerance.

### 13.2 Strategy correctness

- Each strategy has a version, parameters, timeframe and market-universe specification.
- Each entry/exit is a deterministic function of data available at decision time.
- A completed-candle signal is not emitted from a forming candle.
- Breakout thresholds exclude the active candle.
- Signals are idempotent: reprocessing the same finalized candle must not create duplicate trades or alerts.
- `BUY`, `EXIT`, `WAIT`, `AVOID`, `STALE_DATA` and `NO_SIGNAL` have documented meanings.
- A strategy that fails data quality or risk checks must not issue an actionable entry.

### 13.3 Backtest correctness

- Include commissions, taxes/fees, spread, slippage and realistic fills.
- Prevent same-close fills unless the simulator models an executable closing-auction order placed before the relevant cutoff.
- Handle overnight gaps and ambiguous intrabar stop/target events conservatively.
- Include delisted names and historical membership where possible.
- Persist strategy code/version hash, parameter set, data snapshot and cost-model version for every run.
- Produce reproducible results from the same data and configuration.

### 13.4 Signal auditability

For every generated signal, store:

```text
signal_id
instrument_id
strategy_id
strategy_version
parameter_hash
timeframe
decision_time_utc
source_candle_close_time_utc
data_source
input_snapshot_or_hash
indicator_values
conditions_passed
conditions_failed
signal_state
entry_reference
stop_reference
risk_budget
suggested_quantity
reason_codes
created_at_utc
```

This allows Tradely to explain exactly why a signal appeared and to investigate later discrepancies.

---

## 14. Development roadmap

### Phase 1 — Reliable EOD research foundation

- Add provider abstraction and instrument master for NSE/BSE, US-first international equities and crypto spot.
- Add a private-prototype EOD provider adapter (yfinance) and an optional India EOD adapter (TejHQ, subject to terms).
- Create historical OHLCV storage with market-specific calendars.
- Add corporate-action handling and data-quality checks.
- Implement indicator formulas and unit tests.
- Build a simple watchlist and stock-analysis page.

**Exit criterion:** a selected daily candle produces independently verified indicator values and reproducible historical data.

### Phase 2 — First strategy engines

- Implement momentum ranking.
- Implement SMA trend filter.
- Implement Donchian breakout.
- Implement ATR stops and position sizing.
- Add rule-by-rule signal explanations.

**Exit criterion:** strategy outputs are deterministic, explainable and free of look-ahead in controlled tests.

### Phase 3 — Backtest and research lab

- Add execution simulator.
- Add dated fee configurations.
- Add point-in-time universe membership.
- Add chronological train/validation/test and walk-forward analysis.
- Add experiment registry, multiple-testing diagnostics and reporting.

**Exit criterion:** a strategy can be evaluated net of costs on a point-in-time universe with a locked, untouched test period.

### Phase 4 — Multi-market news, alerts and actual portfolio tracking

- Add instrument-specific news panels for Indian equities, international equities and crypto assets.
- Add GDELT global news discovery, permitted publisher RSS feeds, US SEC filing ingestion and official Indian exchange/issuer links.
- Add stock-specific corporate-event rows inside each equity analysis page; do not create a calendar page.
- Add deterministic price/indicator alerts with source freshness checks.
- Add actual-holdings portfolio tracking via manual transactions or CSV import; no simulated holdings, simulated fills or paper-trading account.
- Add a trade journal for user-entered real trades, kept separate from system signals and backtest results.

**Exit criterion:** news items are linked to the correct instrument with source and timestamp traceability; user-entered holdings reconcile correctly; no simulated account or order execution exists.

### Phase 5 — International and crypto data adapters

- Add US-first international equity coverage through the selected permitted source(s); add further countries only after verifying their symbol coverage, calendars, corporate actions and data rights.
- Add SEC EDGAR company filings and issuer investor-relations release links for US companies.
- Add Binance public crypto market data and CoinGecko aggregate fallback with provider/venue labels.
- Add a 24/7 UTC crypto candle scheduler and venue-aware cost/liquidity model.
- Add optional Twelve Data and Alpha Vantage adapters with hard quota limits and endpoint entitlement checks.

**Exit criterion:** data freshness and provider provenance are always visible; international and crypto strategies are independently validated; unsupported symbols fail clearly rather than returning misleading data.

### Phase 6 — Intraday analysis (only with a permitted feed)

- Add intraday data only from a provider whose terms and entitlement permit the intended use.
- Implement intraday VWAP/RVOL/ORB separately from daily strategies.
- Apply session calendars, partial-candle handling, rate-limit control and data-quality guards.

**Exit criterion:** intraday signals are generated only from correctly timestamped intraday candles and are clearly labelled live/delayed according to the provider entitlement.

### Explicitly out of scope

- No public release, SaaS operation, multi-user hosting, user registration, invitations, customer accounts or data sharing. Tradely is for the owner alone.
- No paper-trading account or simulated user positions.
- No automated broker order placement.
- No AI, ML predictions, LLM-based sentiment or black-box scoring.
- No assumption that any provider's free tier permits a public/commercial multi-user deployment.

---

## 15. Product principles

1. **No AI:** no AI-generated predictions, stock grades, sentiment or trading explanations.
2. **Explain every signal:** show the formula, value, threshold, data source and timestamp.
3. **No guaranteed-profit language:** never call a strategy foolproof or risk-free.
4. **Separate strategies:** do not merge distinct setups into one opaque score.
5. **Costs first:** every backtest must include realistic costs and execution assumptions.
6. **Data freshness is visible:** distinguish live, delayed and end-of-day; never infer live status.
7. **No repainting:** finalized signals do not change silently.
8. **Research before deployment:** a strategy can remain experimental indefinitely if evidence is insufficient.
9. **No paper trading or order execution:** Tradely is an analysis, signal, backtesting and actual-holdings tracking tool in this scope.
10. **Version everything:** data, indicator conventions, strategy code, parameters and cost models must be traceable.
11. **Multi-market identity:** distinguish NSE/BSE, international exchanges and individual crypto venues; do not conflate duplicate tickers.
12. **Instrument-specific news:** show company news, filings and upcoming/recent events only inside the relevant equity's analysis page; show project/exchange news inside the matching crypto asset page. No standalone calendar page.
13. **Source traceability:** every news item and event must retain its publisher/official source, original URL, timestamps, relevance classification and freshness state.
14. **No news-driven automatic signals:** news and event information is contextual; deterministic trading rules remain responsible for BUY/SELL/EXIT signals.
15. **Free-provider honesty:** a free key, public endpoint or open-source wrapper does not automatically grant data ownership, redistribution or commercial display rights.
16. **Owner-only privacy:** Tradely is a private single-user application. Do not expose it publicly or provide provider data to other users.
17. **Provider terms still apply:** private use does not waive personal-use terms, rate limits, attribution, retention rules, geographic restrictions or exchange requirements.

---

## 16. Limitations and disclaimer

There is no foolproof trading method. Historical patterns can disappear, transaction costs can overwhelm small edges, markets can gap, data can be inaccurate, and a strategy can lose money even when implemented correctly. Research findings are sample- and methodology-dependent. The proposed rules and parameter values in this document are hypotheses for controlled testing, not proven optimal settings.

Tradely is intended solely for its owner's private quantitative research, analysis, alerting, backtesting and actual-holdings tracking. It is not a public or multi-user service. It does not place orders and has no paper-trading feature in this specification. A generated signal is not a guarantee, personalised investment advice, or an instruction to trade. Users are responsible for verifying current prices, liquidity, exchange/broker requirements, applicable law, taxes and data rights. Do not risk money that you cannot afford to lose.

---

## 17. Research bibliography and official references

### Academic research

1. Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). **Time Series Momentum.** *Journal of Financial Economics*, 104(2), 228–250. [https://doi.org/10.1016/j.jfineco.2011.11.003](https://doi.org/10.1016/j.jfineco.2011.11.003)
2. Sehgal, S., Pandey, A., & Sen, S. (2024 online; 2025 issue). **Relative, absolute or combined strength momentum strategies: what works for India?** *International Journal of Emerging Markets*, 20(10), 4288–4307. [https://doi.org/10.1108/IJOEM-09-2023-1518](https://doi.org/10.1108/IJOEM-09-2023-1518)
3. Bajgrowicz, P., & Scaillet, O. **Technical Trading Revisited: False Discoveries, Persistence Tests, and Transaction Costs.** [Author-hosted PDF](https://www.scaillet.ch/pdfs/BajSca.pdf)
4. Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2017). **The Probability of Backtest Overfitting.** *Journal of Computational Finance*. [https://doi.org/10.21314/jcf.2016.322](https://doi.org/10.21314/jcf.2016.322)
5. Bailey, D. H., & López de Prado, M. (2014). **The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality.** *The Journal of Portfolio Management*, 40(5), 94–107. [https://doi.org/10.3905/jpm.2014.40.5.094](https://doi.org/10.3905/jpm.2014.40.5.094)
6. Hudson, R., & Urquhart, A. **Technical Trading and Cryptocurrencies.** *Annals of Operations Research*, 297, 191–220 (2021). [https://doi.org/10.1007/s10479-019-03357-1](https://doi.org/10.1007/s10479-019-03357-1)

### Indian market and regulatory sources

7. SEBI (July 2024). **Analysis of Intraday Trading by Individuals in Equity Cash Segment.** [SEBI study page](https://www.sebi.gov.in/reports-and-statistics/research/jul-2024/study-analysis-of-intraday-trading-by-individuals-in-equity-cash-segment_84946.html) · [PDF](https://www.sebi.gov.in/sebi_data/attachdocs/jul-2024/1721818140715.pdf)
8. SEBI (20 August 2026). **Profitability of Individual Traders in the Equity Derivatives Segment (FY25–FY26).** [SEBI study page](https://www.sebi.gov.in/reports-and-statistics/research/aug-2026/study-profitability-of-individual-traders-in-the-equity-derivatives-segment-fy25-fy26-_103835.html) · [PDF](https://www.sebi.gov.in/sebi_data/attachdocs/aug-2026/1787233506209.pdf)
9. National Stock Exchange of India. **Market Timings and Holidays.** [Official NSE page](https://www.nseindia.com/resources/exchange-communication-holidays)
10. ICICI Direct. **Breeze API documentation.** [Official docs](https://api.icicidirect.com/breezeapi/documents/index.html)

### Market-data providers

11. TejHQ. **API documentation.** [Docs](https://tejhq.dev/docs) · [Free API key](https://tejhq.dev/keys) · [Data terms](https://tejhq.dev/data-terms)
12. CoinGecko. **API pricing and Demo plan.** [Pricing](https://www.coingecko.com/en/api/pricing) · [API docs](https://docs.coingecko.com/)
13. Binance. **Spot REST API.** [Official developer documentation](https://developers.binance.com/en/docs/products/spot/rest-api)


### Current data, news and licensing references

14. yfinance. **Yahoo Finance data access and personal-use disclaimer.** [Documentation](https://ranaroussi.github.io/yfinance/) · [GitHub](https://github.com/ranaroussi/yfinance)
15. Binance. **Public market-data-only REST and WebSocket endpoints.** [Market-data-only documentation](https://github.com/binance/binance-spot-api-docs/blob/master/faqs/market_data_only.md) · [Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api)
16. CoinGecko. **Demo API pricing, monthly call credits, rate limit and attribution.** [Pricing](https://www.coingecko.com/en/api/pricing) · [Documentation](https://docs.coingecko.com/)
17. Alpha Vantage. **Free request limit and API endpoint documentation.** [Support](https://www.alphavantage.co/support/) · [Documentation](https://www.alphavantage.co/documentation/)
18. Twelve Data. **Basic plan quotas and market coverage.** [Pricing](https://twelvedata.com/pricing) · [Documentation](https://twelvedata.com/docs)
19. U.S. Securities and Exchange Commission. **Free EDGAR access, fair-access limit and User-Agent requirements.** [Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data) · [SEC API documentation](https://www.sec.gov/edgar/sec-api-documentation)
20. GDELT Project. **Open global news/event data and query tools.** [Project data page](https://www.gdeltproject.org/data.html) · [DOC API introduction](https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/)
21. NewsAPI. **Developer plan restrictions: 100 requests/day, 24-hour delay and development/testing-only use.** [Pricing](https://newsapi.org/pricing)
22. NSE India. **Data sharing/usage policy and paid corporate data access.** [NSE Data Policy](https://www.nseindia.com/static/market-data/nse-data-policy) · [Corporate Data Subscription](https://www.nseindia.com/static/market-data/corporate-data-subscription)
23. BSE India. **Market-data and corporate-data feed access.** [BSE Self Data Feed](https://marketdata.bseindia.com/) · [Information Products Pricing Sheet](https://www.bseindia.com/downloads1/Information_Products_Pricing_Sheet.pdf)

---

**Tradely — Research first. Rules over guesswork. Risk before entry.**
