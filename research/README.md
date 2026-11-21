# EMA Pullback V4.2 research engine

The default BTCUSDT input is the Binance USD-M perpetual snapshot covering January 2024 through December 2025. The 2020?2023 prefix initializes indicators and is excluded from trading. The checked archive hashes and historical funding records are in `data/BTCUSDT_USDM/sources.json`. Rebuild it with `python research/build_perpetual_snapshot.py`. The previous OHLCV files and historical gross reports are preserved.

Research starts with 1,000 USDT. Market entries, stops and close exits cost 2 bps per fill. Resting target limits cost 5 bps. Funding uses signed settlement payments and slippage is zero. With custom OHLCV alone, funding is reported as unavailable and zero. Supply bar-open `funding_rate` and `funding_mark_price` or quote-currency payments per long unit in both `funding_open_per_unit` and `funding_inside_per_unit`. Open settlements precede entries. Intrabar price exits precede within-bar funding when timing is ambiguous.

Run the search in the Backtesting page or from the project root. The explicit cutoff below applies to the bundled snapshot.

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff 2026-01-01T00:00:00Z --execution-mode auto --batch-size 4 --max-combinations 20
```

CPU, GPU-first with fallback, and automatic modes share chronological trade settlement. GPU-first requires a compatible NVIDIA runtime and the matching CuPy distribution (for CUDA 12, install the project's `cuda12` extra). Automatic mode uses a provisional 100,000-candle threshold. A result records the backend actually used and its fallback reason. Select optional targets with `--target-r 1.5 2 3`. The default remains 2R.

See [the current audit](NET_ACCOUNTING_AUDIT.md) for validation, benchmarks and limitations. The older overhaul report describes historical gross accounting.

## Research validation commands

Use the same completed candles and net accounting as the strategy analyzer. Each
command prints JSON. A walk-forward configuration file contains an array of
overrides such as `[{}, {"target_r": 1.6}]`. Supply UTC boundaries aligned with the
base candles. The first boundary ends the initial training set and starts the
first holdout.

```powershell
python research/validation_workloads.py walk-forward 2h 2025-01-01T00:00:00Z 2025-07-01T00:00:00Z 2026-01-01T00:00:00Z --configs configs.json
python research/validation_workloads.py monte-carlo path/to/2h_trades.csv --paths 10000 --block-size 5 --seed 42 --mode auto
python research/validation_workloads.py portfolio-backtest 2h 2026-01-01T00:00:00Z datasets.json --capital 1000
```

Walk-forward uses expanding training windows. The highest training net PnL wins,
subject to the minimum trade count. Holdouts start flat and close at each fold
boundary. The combined return compounds the evaluated folds and the report lists
folds that lacked sufficient training trades.

Monte Carlo samples circular blocks from settled trade returns. It measures
terminal return and drawdown at settlement points, with the starting balance as
the first peak. CUDA execution and CPU fallback use the same seed and sampling
rule. These distributions describe resampling of the supplied ledger.

The portfolio dataset file maps symbols to objects with `base`, `htf`, and an
optional `config`. Use inputs in the same quote currency and timeframe. Paths
are relative to that file. Use the `portfolio` command with a JSON map from
symbols to existing trade CSV paths to replay those ledgers directly.

Generate a second symbol's Binance USD-M input with:

```powershell
python research/build_perpetual_snapshot.py --symbol ETHUSDT --history-start 2023-01-01 --output path/to/ETHUSDT_USDM
```

The builder verifies candle archives and expects complete eight-hour funding
settlements by default. When settlement history is unavailable, pass
`--exclude-funding` with a separate output directory. Both the snapshot manifest
and analyzer report record the exclusion.

The `portfolio-backtest` command trades synchronized bars starting at the latest
eligible evaluation start across symbols. Each bar settles open funding on
existing positions, sizes new signals against shared equity at the open, and
reserves entry notional plus fees. Symbol order breaks simultaneous entry ties.
Entries precede same-bar exits and a rejected entry leaves later signals eligible.
Each close reports equity including unrealized PnL, funding and estimated taker
exit fees. A same-symbol signal on an exit bar follows the standalone cooldown.
The `portfolio` command still replays historical trade CSVs and reports realized drawdown.

Pass `--maintenance-rate 0.005` to stress a hypothetical flat 0.5% cross-account
requirement. The check runs after ordinary exits at each bar close. A breach closes
all surviving positions at that close with taker fees. Binance mark-price ticks,
tiered brackets and exchange liquidation fees require additional historical inputs.
Maintenance checks default to disabled. For snapshot-builder CSVs, audit every
reported equity mark independently with Decimal arithmetic:

```powershell
python research/validation_workloads.py portfolio-backtest 2h 2026-01-01T00:00:00Z datasets.json --mode cpu --maintenance-rate 0.005 > portfolio-result.json
python research/verify_joint_portfolio.py portfolio-result.json datasets.json
```

## Installation and tests

Python 3.11–3.14, NumPy and pandas are the runtime dependencies. Development tools
are separate. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r research/requirements-dev.txt
# Isolate the existing backend API tests from the user's application database.
$env:DATABASE_PATH = Join-Path $env:TEMP ('tradely_tests_' + [guid]::NewGuid().ToString() + '.sqlite3')
python -m pytest -o addopts='' -q --cov --cov-report=term --cov-report=xml:research/benchmarks/coverage.xml
python -m ruff check research
python -m mypy
python -m compileall -q research
python -m ruff format --check research/optimization_runtime.py research/benchmark_optimization.py research/tests/fixture_data.py research/tests/test_optimization_runtime.py
```

Linux/macOS equivalents:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r research/requirements-dev.txt
DATABASE_PATH="$(mktemp -u /tmp/tradely-tests-XXXXXXXX.sqlite3)" python -m pytest -o addopts='' -q --cov
python -m ruff check research
python -m mypy
python -m compileall -q research
```

Root pytest discovery includes both backend and research tests. Standalone
`python -m pytest research/tests` and the older unittest entry points still work.
Ruff lint covers all research Python; formatting is enforced on the new modules,
without a formatting-only rewrite of the historical engine/test files. Mypy
checks the analyzer, driver, runtime and benchmark utility. Tests include exact
pre-change numerical/signal/trade goldens, spawn concurrency, failures, retries,
interruption, cutoff integrity and input mutation checks. The compressed golden
fixture records the original engine hash and is not regenerated during tests.

## Architecture

```text
CLI / Python run_search
  -> ranges, exact counts, deterministic candidate IDs, validation
  -> dataset preflight, source hashes, cutoff policy, search signature
  -> exclusive parent writer + bounded scheduler
       -> worker initializer: read/validate each CSV once, resolve cutoff/coverage
       -> analyzer.run_analysis(prepared_data=..., write_outputs=False)
            indicators + convergence -> signals -> same simulator -> same metrics
       <- compact Evaluation (metrics, identity, timing, error; optional audit)
  -> atomic per-candidate records -> checkpoint summary -> streamed CSV exports
  -> bounded top-N selection, metadata, failure history and logging
```

Files have cohesive responsibilities:

- `strategy_analyzer.py`: loading, validation, preparation, indicators, signals,
  execution, sizing, trade/audit records and metrics. Its existing CLI and default
  `run_analysis()` outputs are retained. `PreparedAnalysisData` binds an immutable
  worker-local snapshot to paths, hashes, timeframe and cutoff. `write_outputs=False`
  suppresses all analyzer file writes; `collect_audit=False` suppresses detailed
  per-bar audit construction without changing simulation or trade metrics.
- `v42_exhaustive_combination_tester.py`: configurable ranges, mapping, lazy search,
  exact counts, identity, ranking, parent reporting and CLI. `run_search()` returns
  a dictionary whose `rows` is now a disk-backed Mapping; use `dict(rows)` only for
  intentionally small workloads. Existing helper APIs remain available.
- `optimization_runtime.py`: picklable worker interface, `ProcessPoolExecutor`,
  atomic result storage and OS-owned writer lock. It contains no trading rules.
- `benchmark_optimization.py`: reproducible limited 1/2/4-worker measurement and
  profiling. `tests/fixture_data.py` supplies explicitly synthetic test data.

`--workers` defaults to **4**. `--workers 1` uses the same optimized analyzer in the
parent process as a sequential reference. Two or more workers use explicit
`spawn` on every OS, with top-level functions and guarded entry points. Do not
call `run_search()` from another worker or concurrently from threads. Python
callers starting multiple processes must protect their own entry point with
`if __name__ == '__main__':`.

At most `2 * workers` tasks are submitted. Only configuration dictionaries and
small execution metadata cross the queue. Workers never write result files.
Each worker caches at most two indicator/convergence frames, keyed by all six
relevant periods (fast/medium/slow EMA, ADX, ATR, HTF EMA), scoped to its exact data,
cutoff and engine. A single signal frame is reused for adjacent exit-only variations. Positions are sized independently for every candidate.
Cached frames are copied before adding signals; no mutable DataFrame is shared
between workers. BLAS/OpenMP child thread limits are set to one before spawn and
the parent's environment is restored afterward. No affinity/system settings change.

Four workers are conservative for 16 GB on the measured fixture; actual memory
scales with dataset size. Reduce workers if large datasets exceed available RAM.
The parent streams compact result records and retains only a top-N heap; it never
keeps all trade histories or submits the whole Cartesian product. Checkpoint files
are sharded by ID prefix; export sorts filenames one shard at a time. File count
and resume scanning time will eventually become limiting at millions of results.

## Data and cutoff integrity

| Base timeframe | Default base CSV in `research/data/BTCUSDT_USDM/` | HTF CSV |
|---|---|---|
| 2h | BTCUSDT_2hours.csv | BTCUSDT_1day.csv |
| 4h | BTCUSDT_4hours.csv | BTCUSDT_1day.csv |
| 1d | BTCUSDT_1day.csv | BTCUSDT_1week.csv |

Custom datasets can be supplied with `--base` and `--htf`. The bundled source manifest records the verified cutoff.

Strict mode is the default and requires an explicit, timezone-qualified,
**independently verified** `--data-cutoff`. Supplying a timestamp asserts the
caller's verification; the program does not contact an exchange to establish it.
The cutoff must lie within available data. Merely reaching a candle's expected
close does not independently verify its completion.

Diagnostic mode is explicitly unverified, including when an explicit cutoff is
provided. Without one it uses the final base candle's **open**, excluding that
candle. Base candles are included only when their full duration ends by the
cutoff. HTF candles also require exchange-boundary alignment and complete
underlying-base coverage. Weekly periods start Monday UTC; month handling remains
calendar-aware. No missing candles are invented. Warm-up and independent
convergence checks remain authoritative. Gap-crossing trades retain their flags
and the analyzer's affected/unaffected sensitivity metrics.

The optimizer additionally rejects unordered/duplicate timestamps, missing or
non-finite OHLCV, negative volume and misaligned candles before starting workers.
The analyzer's legacy default loader retains its reported normalization behavior
for API compatibility. These stricter optimizer input checks do not change the
strategy on valid inputs. CSVs are never modified. Both hashes and stat checks bind
workers to preflight inputs; changing datasets requires a new search identity.

## Parameters and search size

Edit `PARAMETER_RANGES` near the top of the driver or pass `--ranges ranges.json`
containing the same 15 keys, each with `min`, `max`, `step`. Endpoints are inclusive,
including the maximum when the step does not land on it. Integer parameters need
integer bounds and steps. Unknown keys and invalid values fail before execution.

| Tester name | Approved range | Default step | Analyzer key |
|---|---:|---:|---|
| fast_ema | 5–40 | 5 | fast_ema |
| medium_ema | 20–100 | 10 | medium_ema |
| slow_ema | 100–365 (1D cap 250) | 25 | slow_ema |
| adx_period | 7–28 | 3 | adx_period |
| adx_min | 15–30 | 3 | adx_min |
| atr_period | 7–28 | 3 | atr_period |
| htf_ema | 20–100 | 10 | htf_ema |
| pullback_n | 2–10 | 2 | pullback_n |
| pullback_depth_atr | 0–1 | 0.10 | pullback_depth_atr |
| trigger_close_location | 0.55–0.80 | 0.05 | trigger_close_long=v; trigger_close_short=1−v |
| stop_buffer_atr | 0.10–1 | 0.10 | stop_buffer_atr |
| min_stop_atr | 0.25–1 | 0.25 | min_stop_atr |
| max_stop_atr | 1.5–4 | 0.5 | max_stop_atr |
| chandelier_atr | 1.5–5 | 0.5 | chandelier_atr |
| time_stop | 10–60 candles | 10 | time_stop |

Fast < medium < slow and minimum stop < maximum stop are enforced. Target defaults to 2R. Explicit target lists expand the grid. Risk percentage, leverage cap, all other baseline values and exposure
constraints are not optimized. All 15 names are explicitly mapped.

Default valid counts are **9,827,470,540,800** for 2H/4H and
**5,688,896,716,800** for 1D. Counts are factorized exactly without enumeration.
Generation is lazy in the canonical parameter order and prunes invalid EMA
prefixes before visiting their huge suffixes. Limits count newly attempted valid
configurations, including failures, not previously successful checkpoints.
A limited run is an exhaustive **prefix**, biased toward low values of early
axes, not a representative random sample. No alternative methodology is enabled.
`--plan` shows axis sizes, Cartesian and valid counts, sample candidates and cutoff.

## Execution commands

PowerShell, after independently verifying a real cutoff and restoring datasets:

```powershell
# Replace this example with the independently verified cutoff for your files.
$cutoff = '2026-01-01T00:00:00Z'
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --plan
# 20-configuration smoke test; separate output roots avoid overwriting runs.
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 20 --workers 4 --output research/optimization/smoke
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 20 --workers 1 --output research/optimization/one_worker
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 20 --workers 2 --output research/optimization/two_workers
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 20 --workers 4 --output research/optimization/four_workers
# Larger limited search, then resume (same data, engine, ranges and ranking).
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 1000 --workers 4 --output research/optimization/limited
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --max-combinations 1000 --workers 4 --output research/optimization/limited --resume --retry-failed
# Optional: --resume-run <16-character-search-id> names an exact original run.
# Explicit full search; enormous default space. Not run during implementation.
python research/v42_exhaustive_combination_tester.py --timeframe 2h --data-cutoff $cutoff --workers 4 --full-search --output research/optimization/full
```

The same one-line commands work on Linux/macOS with `cutoff='...'` instead of the
PowerShell assignment (and `python3` when appropriate). `--timeframe all` processes
2H, 4H, 1D in sequence; each timeframe uses its own bounded process pool.

Without market data, reproduce the **synthetic** smoke benchmark:

```powershell
python research/benchmark_optimization.py --count 20
python research/benchmark_optimization.py --count 100
```

These commands create isolated `research/benchmarks/run_<unique-id>/` folders,
including synthetic input CSVs, profiles, optimizer outputs and `benchmark.json`.
They never claim independently verified market results. Supply `--base`, `--htf`
and `--timeframe` to benchmark real datasets in diagnostic mode. Optional
`--baseline-source path/to/original/strategy_analyzer.py` measures the original
report-writing path alongside the refactored path. The original source is available
in Git commit `a8963ca`; the committed goldens were captured before editing it.

## Recovery, output and ranking

```text
optimization/
  configs/<timeframe>/<search-id>.json
  checkpoints/<timeframe>/<search-id>.jsonl  # derived compatibility export
  logs/<timeframe>/<search-id>.log
  results/<timeframe>/<search-id>/
    search_config.json, run_metadata.json, checkpoint.json
    all_results.csv, top_configs.csv, failed_combinations.csv
    records/<first-two-id-digits>/<config-id>.json
    failures/<config-id>_<attempt-id>.json
    audits/<config-id>.json                 # only if requested
```

The per-result record is fsynced and atomically replaced immediately after every
completed evaluation. A periodic checkpoint summary defaults to every 10 commits.
Interrupted/hard-killed runs recover from `records/`, including results newer than
the last summary. CSV and JSONL exports are atomically replaced at normal or
graceful-interruption completion; during a hard crash they can lag the records.
Never remove records to make a mismatch disappear. Corrupt records fail clearly.
An OS-owned writer lock prevents concurrent parents and releases on process death.
Filesystem power-loss guarantees ultimately depend on the OS/filesystem; fsync and
atomic replace protect ordinary process interruption, not arbitrary hardware failure.

Ctrl+C stops submission, cancels queued work and drains already running jobs.
Draining can take one candidate duration; there is no forced per-candidate timeout.
A broken process pool records affected configurations as errors, saves completed
work and exits with failure. Resume with `--retry-failed` retries errors; otherwise
errors remain visible and are skipped, never counted as successful. Retry history
is retained. CLI exit codes: 0 normal/capped completion, 1 candidate/pool errors,
2 invalid input/resume, 130 interruption.

Search identity covers timeframe, input hashes, exact cutoff and verification,
engine and optimizer hashes, runtime versions, ranges/steps, ordering, exhaustive
methodology and ranking criteria. `--resume-run ID` reports incompatible fields.
Worker count and invocation cap can change on resume. Source changes intentionally
prevent resuming old-engine runs, including the preserved original 517-result run.
New runs never overwrite an existing identical signature without explicit resume.

Ranking defaults to net PnL with at least ten trades. Net return, net profit factor, Sharpe, net expectancy and drawdown-adjusted return are also available. Positive gains with zero losses produce `infinite` profit factor. The optimizer preserves gross-R diagnostics as explicitly named optional rankings. Each row records the fee rates, funding model, dataset and source identity.

Use `--audit-config <config-id>` for candidates evaluated in that invocation.
Existing successful candidates are not rerun merely to add an audit; reproduce a
selected candidate with the analyzer in a fresh output directory instead. Large
audits are opt-in and can substantially increase IPC and disk use.

Progress reports successful, failed and active-or-queued tasks separately, remaining
successful evaluations, worker count, elapsed/average evaluation time, evaluations
per minute, invocation ETA and last completed configuration ID. Submission does
not increment completion. Refreshes are limited to once per second; the legacy
`--progress-every 0` disables updates, positive values enable them. `--quiet`
suppresses normal console output; `--log-level` controls console/file severity.

## Historical gross-engine measurements

On the deterministic 6,000-candle synthetic fixture (Windows, 16 logical CPUs):

| Configurations | Original sequential | Optimized 1 worker | 2 workers | 4 workers |
|---:|---:|---:|---:|---:|
| 20 | 12.44 s | 2.04 s | 1.53 s | 1.38 s |
| 100 | 64.49 s | 9.72 s | 5.21 s | 3.37 s |

The 100-configuration four-worker run used about 421 MiB aggregate RSS and was
2.88x faster than optimized sequential, 19.11x faster than the old report-writing
path. This cache-friendly exhaustive prefix is synthetic, not a market-data
performance guarantee. A single candidate was faster in-process (0.388 s) than
with spawn (about 0.8 s). See [the detailed report](OVERHAUL_REPORT.md) for CPU,
initialization, profiling, hashes, limitations and reproducibility commands.

## Limits and next research steps

Historical optimization can overfit and does not guarantee future performance.
The top-ranked prefix candidate is not a validated winner. Keep selection and
held-out validation datasets/experiment roots separate; include adequate warm-up
history when designing validation windows. No automatic split, walk-forward or
multi-period stability score is implemented. The worker interface and distinct
hashed input snapshots support future experiment orchestration without another
simulator. Random/coarse-to-fine/staged methods would require an explicit method
identity and distinct result labels.

The net-engine benchmark and current limitations are in [the net accounting audit](NET_ACCOUNTING_AUDIT.md). SIMD-style array operations use NumPy on CPU and optional CuPy on CUDA. Recursive Wilder and EMA calculations use their original CPU definitions. Large searches still create one durable record per configuration.

For browser integration, build the frontend, install Playwright in the test environment and run `python -m pytest frontend/tests/test_research_browser.py`. Set `PLAYWRIGHT_CHANNEL=msedge` to use an installed Microsoft Edge, or install Playwright Chromium.
