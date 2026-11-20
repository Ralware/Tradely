# Tradely net accounting and exhaustive search audit

## Outcome

The EMA Pullback analyzer, exhaustive CLI, browser search, checkpoint records and CSV exports now use per-fill net accounting. The financial ledger passed independent settlement reconciliation on the bundled BTCUSDT perpetual dataset. CPU optimization improved on the measured fixture. Physical NVIDIA performance and CPU/CUDA financial parity remain unverified. The full production-readiness definition is open.

## Findings and corrections

| Severity | Affected area | Root cause and correction |
|---|---|---|
| Critical | research/strategy_analyzer.py | Gross PnL previously increased the next trade's sizing balance. Each entry and exit now incurs its own fee. Subsequent trades use settled net equity. |
| Critical | research/data, research/build_perpetual_snapshot.py | The previous inputs did not establish perpetual venue and historical settlement provenance. The default snapshot uses 72 checksum-verified Binance USD-M monthly two-hour archives and 2,193 funding records. Larger timeframes aggregate completed bars. |
| High | research/strategy_analyzer.py | Reports exposed missing fees and funding and audit rows showed zero costs. Trade records and audit rows now carry actual fill classifications, fees, signed funding and zero slippage. Missing funding inputs have a distinct exclusion status. |
| High | research/strategy_analyzer.py | Drawdown used trade-close balances. Bar-end equity now includes entry costs, open PnL, funding and estimated market-close costs. Exit bars use the actual fill. Risk ratios use net bar returns after warm-up. |
| High | research/v42_exhaustive_combination_tester.py | The default leaderboard optimized gross R. New results default to net PnL. Other net rankings, fee assumptions, input hashes and execution metadata survive export and restart. Engine and search signatures separate historical results. |
| High | backend/app/services/backtest.py | A later intrabar stop could supersede an exit already due at the open. The pending open exit now executes first. Open-position equity includes closing costs, and drawdown includes the initial balance. |
| High | backend/app/providers/tradingview.py | Weekly and monthly crypto bars inherited equity closing rules. Crypto finality now follows UTC period boundaries. Indian weekly/monthly cutoffs use the local market clock. |
| High | backend/tests/conftest.py | Importing the application in tests could write to the local portfolio database. API tests now use a temporary database. The initial test run touched the tracked database. It was restored to the clean starting version and SQLite integrity was checked. |
| Medium | research/optimization_runtime.py, research/exit_paths.py | Per-candidate dispatch and repeated Python bar replay added overhead. The bounded pool now dispatches batches. Independent exit paths are calculated in arrays, followed by chronological sizing and settlement. Single-worker state is thread-local. |
| Medium | research/strategy_analyzer.py | Exit-only variations regenerated identical signals. Each worker retains a bounded indicator cache and its most recent signal frame. |
| Medium | research/v42_exhaustive_combination_tester.py | The fixed target excluded take-profit sweeps. The baseline still uses 2R, and explicit target lists expand the grid. Tests enumerated 45,000 distinct configurations. |
| Medium | backend/app/api/research.py, frontend/src/components/analysis/ResearchSearch.tsx | Exhaustive testing had no browser workflow. The Backtesting page now launches, polls, cancels, resumes and exports the existing CLI search, including fallback reasons and displayed net results. |
| Medium | backend/app/core/models.py, backend/app/api/routes.py, frontend/src/pages/BacktestingPage.tsx | Daily-strategy defaults differed between entry points. Defaults now use 1,000 starting capital, 2 bps market fills and zero slippage. The UI labels net profit factor and restores the most recent daily result. The existing equity/spot strategy retains explicit cost overrides and its own market data. |
| Medium | research/strategy_analyzer.py, research/data/BTCUSDT_USDM | Two years alone gave the daily strategy insufficient convergence history. The snapshot includes a 2020–2023 warm-up-only prefix. Trading is eligible in 2024–2025 after convergence. |

## Accounting conventions

The shared fee schedule in backend/app/core/fills.py charges 0.0005 of maker notional and 0.0002 of taker notional. Research market entries, market stops and close exits are taker fills. Resting targets, including gap-through target limits, are maker fills at the limit price. Monetary calculations retain floating-point precision internally. Presentation applies rounding. Trade return uses entry notional, and aggregate return uses initial capital.

Positive funding denotes a payment. The exchange funding rate times its settlement mark gives quote currency paid per long unit. Shorts reverse the sign. Open settlements precede new entries. Time/data-end exits occur at the close. For price-triggered intrabar exits, the model assumes the exit precedes later funding inside that candle. Holding hours use the open boundary for intrabar events. Exact intrabar times are unavailable. Bar-end drawdown does not measure intrabar peak-to-trough loss.

The source manifest contains original rates, marks, exchange timestamps and archive digests in [sources.json](data/BTCUSDT_USDM/sources.json). The independent test recomputes balances from those records with Decimal and compares them to the engine at every trade.

| Baseline timeframe | Trades | Gross USDT | Maker fees | Taker fees | Funding paid | Net USDT | Drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2h | 69 | 15.409114 | 3.526839 | 8.369360 | 1.453760 | 2.059154 | −5.361448% |
| 4h | 49 | 16.965591 | 1.877896 | 5.522020 | 2.762978 | 6.802698 | −5.265537% |
| 1d | 2 | −7.172181 | 0 | 0.144841 | −0.346793 | −6.970229 | −1.595830% |

## Execution and performance

The audited scalar path preserves the original chronological stop/target ordering. The compact path evaluates independent hypothetical exits, then admits actual positions in time order. NumPy and optional CuPy support array operations. CUDA can process rolling pullback and stop windows, candidate exit paths and net equity marks. Recursive EMA/Wilder initialization, signal assembly, position sizing and settlement stay on CPU. Device working sets are chunked using free memory. Initialization and device-memory failures fall back to CPU. Automatic selection uses a provisional 100,000-bar threshold. Manual GPU requests attempt CUDA on smaller inputs.

The table compares the existing optimizer at commit 39520ab with the revised optimizer. Both evaluated the same 20 configuration IDs, 6,000 synthetic base candles and matching input hashes on Windows, AMD Ryzen AI 7 350, 16 logical CPUs. Times include process startup and output. These are single-run observations on a cache-friendly prefix.

| Workers | Original seconds | Revised CPU seconds | Speedup | Configurations/s | Candles/s | Revised peak aggregate RSS MiB | GPU requested, CPU fallback seconds |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 11.086 | 4.488 | 2.47× | 4.46 | 26,739 | 93.5 | 5.711 |
| 2 | 5.635 | 3.430 | 1.64× | 5.83 | 34,990 | 251.7 | 3.430 |
| 4 | 3.842 | 3.161 | 1.22× | 6.33 | 37,966 | 412.9 | 3.327 |

Raw measurements include CPU utilization, initialization, export time, fixture hashes and configuration IDs. The GPU-requested run used CPU throughout. Physical CUDA time, utilization, memory and speedup are unmeasured. The benchmark does not isolate queue overhead from the other parent-process work. [Benchmark results](benchmarks/net_accounting_comparison.json)

## Verification

| Suite or check | Passed | Failed | Skipped |
|---|---:|---:|---:|
| Backend pytest, including portfolio, database, providers and research API | 165 | 0 | 0 |
| Research pytest, including cutoff integrity, parallel recovery and ledger reconciliation | 187 | 0 | 1 |
| Frontend Vitest | 35 | 0 | 0 |
| Built frontend, Playwright against local API in Microsoft Edge | 1 | 0 | 0 |
| **Total** | **388** | **0** | **1** |

The skipped test requires a physical CUDA device. This machine exposes AMD Radeon 860M graphics. CPU fallback and injected GPU initialization and memory failures passed. The browser integration covered launch, refresh, row-level net PnL against CSV, cancellation and resume. An earlier browser run caught CSS capitalization changing displayed configuration IDs. The final browser run passed after fixing the table style. The frontend type-check and production build, configured research mypy checks, research lint, vendored TypeScript no-emit compilation and bridge syntax check succeeded. Python emitted 25 dependency/deprecation warnings in the full test run.

The original golden data remains intact. Its signal/indicator digests and fill chronology still provide regression evidence. The revised tests independently price the changed fees and balances. The kernel parity suite exercises dual-touch candles, gap stops, targets, data-end exits and historical settlements. The hardware test compares indicators and signals exactly and checks equity within 1e−12 relative and 1e−9 absolute tolerance.

## Files and dependencies

- Research implementation changed in strategy_analyzer.py, optimization_runtime.py, v42_exhaustive_combination_tester.py and benchmark_optimization.py. New research files include exit_paths.py, build_perpetual_snapshot.py, four timeframe CSVs and their source manifest. The research README describes operation and recovery.
- Backend changes span the daily backtest service, request model, API routes, provider finality and router registration. The fill schedule and research API router are new.
- Frontend changes include the Backtesting page, API result types, the new ResearchSearch component, corrected favicon type and rebuilt production assets.
- New tests cover net accounting, research API jobs and browser integration. Existing sizing, analyzer, exhaustive-search, optimization, provider and reference tests were updated. Backend tests gained database isolation.
- pyproject.toml adds optional CUDA 12 CuPy and benchmark psutil extras. CPU execution uses the existing NumPy/pandas stack. The browser integration uses Playwright in a separate test environment. No runtime dependency was removed.

## Open validation and scope

Physical GPU benchmarking and parity verification remain the release gate for CUDA claims. Run the physical parity test and benchmark on a supported NVIDIA host before setting a measured automatic crossover. The 45,000-combination grid was enumerated and a search of that size was cancelled in a browser smoke test. A complete timed 45,000-configuration sweep was not executed.

This review covered the application research and backtesting paths, provider candle finality, persistence, API and frontend integration. Portfolio FIFO, database operations, quotes, strategy configuration and indicators were exercised by their existing suites. The vendored TradingView SDK received a compilation check. A line-by-line audit of every application and vendor module, live broker/exchange integrations and cross-platform execution remain unverified.

The ledger models a capped, single-position strategy. Partial-fill fee arithmetic is covered, while exchange matching, partial-fill generation, maintenance-margin liquidation and queue position are outside the simulator. The Windows host exercised process spawning and cancellation. Walk-forward selection, Monte Carlo paths, concurrent multi-symbol portfolio accounting and portfolio-level CUDA benchmarks were not implemented. These require explicit fold selection, sampling and portfolio capital-allocation semantics before their financial results can be compared. GPU benchmarking, these workloads and the full-repository review remain outstanding against the original brief.

## Continuation handoff

The working tree contains the implementation and rebuilt frontend described above. No commit has been created. On the next session, start with `git status --short` and preserve the existing changes. Prioritize a physical NVIDIA run of `research/tests/test_net_accounting.py`, then measure CUDA and CPU on identical inputs and investigate any parity differences. Next, run and time a complete 45,000-configuration search, review recovery and output completeness, and finish the remaining repository audit. Walk-forward, Monte Carlo, multi-symbol portfolio simulation and their validation remain open. The account usage percentage is not visible to the agent, so the requested 4% stopping point could not be measured.
