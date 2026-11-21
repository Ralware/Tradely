# Tradely work handoff

Prepared November 21, 2026. This summarizes work performed on November 20 and 21 for the codebase audit, financial accounting, exhaustive optimization, GPU support, and test request.

## Repository status

- Repository is C:\tradely\Tradely on branch main.
- November 20 changes were committed and pushed to origin/main in commit e9eeb44, "Add net accounting and batched research optimization".
- The first November 21 continuation was committed as `5b5fe18` and merged with the remote changes in `2b809d1`. That merge was pushed to origin/main.
- The untracked .vscode/ directory existed when the continuation started and was preserved.
- The original request is in C:\Users\gunji\Downloads\message (1).txt. The requested work is still incomplete.

## Completed work

- Implemented per-fill research accounting with 1,000 USDT starting capital, maker fee 0.05%, taker fee 0.02%, and zero slippage. Market entries, stops, and close exits use taker fees. Resting target exits use maker fees. Gross PnL, entry and exit fees, funding, net PnL, and position data are retained per trade.
- The research engine compounds net equity. It reports gross and net statistics separately. Net bar equity includes unrealized PnL, entry fees, estimated market-close costs, and funding. Drawdown and risk metrics use this equity.
- Added a BTCUSDT Binance USD-M perpetual snapshot covering 2024 and 2025 for evaluation, with 2020 through 2023 used only for warm-up. Archive checksums and original funding records are in research/data/BTCUSDT_USDM/sources.json.
- Added CPU batching, cached indicators and signals, CUDA-capable array operations with CPU fallback, and net-PnL default ranking to the existing optimizer. Search signatures bind code, data, cutoff, and parameters. Checkpoints and exports preserve execution assumptions.
- Added a Backtesting-page research search with execution mode, hardware information, progress, cancellation, resume, CSV download, and net results. Updated the daily backtest cost accounting and equity curve, fixed exit priority, and corrected crypto weekly/monthly candle finality.
- Added walk-forward selection, seeded block-bootstrap Monte Carlo, and multi-symbol shared-cash replay in research/validation_workloads.py. The snapshot builder can fetch another USDT perpetual symbol and can explicitly exclude unavailable funding.
- Added tests, a sweep verifier, updated documentation, and an audit report.

## Validation and measurements

- A full 45,000-configuration BTCUSDT 2-hour CPU sweep completed with zero failures. It simulated 3,462,434 trades across configurations and took 856.27 seconds using 10 workers and batches of 12.
- The verifier matched every configuration against the grid, atomic records, CSV and JSONL checkpoint. It checked fees and net PnL, provenance, and leaderboard order. Maximum net-PnL reconciliation residual was 8.53e-14 USDT.
- Resuming the full sweep reused all 45,000 checkpoints, evaluated zero new configurations, and reproduced the CSV SHA-256 digest. The complete CSV and checkpoints are under the local Windows temporary directory at C:\Users\gunji\AppData\Local\Temp\tradely-45000-e9eeb44. They are not included in the Git commit. The compact evidence file is research/benchmarks/net_accounting_45000.json.
- A two-fold walk-forward example evaluated 35 holdout trades. A 10,000-path bootstrap ran on CPU fallback. A BTCUSDT and ETHUSDT shared-cash smoke test settled 132 trades. ETH funding was explicitly excluded because the Binance funding endpoint timed out.
- The full Python regression run passed 359 tests and skipped 2 CUDA tests. A later snapshot funding-exclusion test passed in a targeted rerun. Frontend Vitest passed 35 tests and the browser integration passed 1 test. Research lint, configured mypy, vendored TypeScript type-check and bridge syntax check passed. The full backend lint reported 84 existing findings, mainly style and import ordering.
- On a 20-configuration synthetic benchmark, the revised CPU implementation was 2.47 times faster with one worker and 1.22 times faster with four workers than the previous optimizer. Raw measurements are in research/benchmarks/net_accounting_comparison.json.

## Pending and limitations

- Physical NVIDIA CUDA parity and GPU benchmarking remain unverified. This machine has AMD Radeon 860M graphics. CPU fallback was tested. Automatic CUDA selection uses a provisional threshold. CPU and GPU financial parity cannot yet be claimed.
- The full line-by-line repository and vendor audit, live exchange integration, and cross-platform testing remain incomplete. The audit report identifies which paths were reviewed and what was tested.
- The CSV replay still reports realized drawdown. The local `portfolio-backtest` command now simulates competing signals with a shared wallet, bar-close marks and an optional flat maintenance-margin stress scenario. Exchange-specific liquidation still requires historical margin brackets and a mark-price series.
- Exchange queue position and actual partial-fill generation are not simulated. Partial-fill fee arithmetic was tested. Intrabar funding and exit timing rely on the assumptions documented in the audit.
- The attached original brief requested broad production-quality financial verification and GPU benchmarks. Do not describe that definition of done as achieved until the outstanding work is complete.
- The 45,000-grid result is one specified parameter grid and dataset. It is not an out-of-sample validation of the best strategy.

## Key files

- research/NET_ACCOUNTING_AUDIT.md contains findings, assumptions, test details, and limitations. Its "Scope at the initial checkpoint" section records the earlier status. The later continuation section supersedes its statements about the unfinished 45,000 run and missing validation workloads.
- research/README.md documents the optimizer and validation commands.
- research/strategy_analyzer.py, research/exit_paths.py, research/optimization_runtime.py, and research/v42_exhaustive_combination_tester.py contain the research engine and optimizer.
- research/validation_workloads.py contains the new validation commands. research/verify_cpu_sweep.py verifies sweep records and exports.
- backend/app/core/fills.py contains the fee schedule. backend/app/api/research.py and frontend/src/components/analysis/ResearchSearch.tsx implement the browser search.

## Latest local CPU work

The joint BTCUSDT and ETHUSDT run used 1,000 USDT and a hypothetical 0.5% maintenance threshold. It settled 132 trades and ended at 987.16790676 USDT. Marked drawdown was 9.63735432%. ETH funding was excluded and BTC funding used the bundled historical settlements. A separate Decimal verifier priced every trade and all 8,772 closes against the source candles. The largest equity discrepancy was 1.13e-12 USDT. Reproduction commands are in research/README.md and the input hashes, configurations and residuals are in research/benchmarks/joint_portfolio_cpu.json.

SQLite validation and FIFO reporting now share the same quantity tolerance. Regression tests check rollback for a fractional oversell and overcover. The backend and research lint checks pass. The manual review of every application and vendor source file is still open. Physical CUDA parity, GPU performance and cross-platform execution remain unverified.

Latest validation on Windows passed 364 Python tests, 35 frontend tests and one Edge integration test. Two physical CUDA tests skipped. Python 3.12 and 3.14 produced identical portfolio trades and equity curves. The frontend build, configured static checks and read-only SQLite integrity checks passed.
