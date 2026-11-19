# EMA Pullback V4.2 — Research Analyzer and Combination Tester

## Integrated files

```text
Tradely/
└── research/
    ├── strategy_analyzer.py                  # authoritative V4.2 engine
    ├── v42_exhaustive_combination_tester.py  # search driver (calls the engine)
    ├── requirements.txt
    ├── FILE_HASHES.json
    ├── data/
    │   └── BTCUSDT/
    │       ├── BTCUSDT_2hours.csv
    │       ├── BTCUSDT_4hours.csv
    │       ├── BTCUSDT_1day.csv
    │       ├── BTCUSDT_1week.csv
    │       └── ... (other timeframes retained for future research)
    ├── optimization/                         # new search outputs only
    │   ├── configs/
    │   ├── checkpoints/
    │   ├── logs/
    │   └── results/
    │       ├── 2h/
    │       ├── 4h/
    │       └── 1d/
    ├── results/                              # frozen historical research
    │   ├── v42/
    │   │   ├── 2h/
    │   │   ├── 4h/
    │   │   └── 1d/
    │   ├── v42_bugfix_1/
    │   │   ├── 2h/
    │   │   ├── 4h/
    │   │   └── 1d/
    │   └── v42_bugfix_2/
    │       ├── 2h/
    │       ├── 4h/
    │       └── 1d/
    └── tests/
        ├── test_strategy_analyzer.py
        ├── test_integration_v42.py
        ├── test_bugfix_regressions.py
        ├── test_cutoff_integrity.py
        └── test_combination_tester.py
```

`strategy_analyzer.py` remains the **single source of truth** for indicators,
signals, sizing, stops, targets, exits and PnL. The tester contains no
backtesting logic of its own; it only generates configurations, calls
`strategy_analyzer.run_analysis()`, and stores the results.

The analyzer and tester use the existing datasets in `research/data/BTCUSDT/`.
They do not download, rename, modify, or fabricate candles.

## Important cost/funding scope

Per instruction, historical funding-rate data and exchange fee/slippage
assumptions are excluded.

Therefore this version:

- Does not charge or credit funding.
- Does not apply exchange fees or slippage.
- Reports gross PnL and gross R only. It does not create or label any metric as
  net performance.
- Uses Spot OHLCV as a research input.
- Labels SHORT PnL as hypothetical/signal-only, not executable Spot trading.

Do not use these gross results to claim that V4.2 is profitable after trading
costs.

## Installation

From the Tradely project root, use a Python 3.11–3.14 environment (the
repository's `.venv` is already suitable):

```powershell
.\.venv\Scripts\python.exe -m pip install -r research/requirements.txt
```

If the project environment is already active, the shorter form also works:

```powershell
pip install -r research/requirements.txt
```

Python 3.15 is not supported by the project because pandas has no wheel for it
yet.

## Data used

| Strategy timeframe | Base candle file | Higher-timeframe file |
|---|---|---|
| 2H | `research/data/BTCUSDT/BTCUSDT_2hours.csv` | `research/data/BTCUSDT/BTCUSDT_1day.csv` |
| 4H | `research/data/BTCUSDT/BTCUSDT_4hours.csv` | `research/data/BTCUSDT/BTCUSDT_1day.csv` |
| 1D | `research/data/BTCUSDT/BTCUSDT_1day.csv` | `research/data/BTCUSDT/BTCUSDT_1week.csv` |

The loader supports timestamp/open/high/low/close/volume CSVs and Binance's
headerless 12-column kline CSVs. Millisecond, microsecond, nanosecond and
second timestamps are detected and converted to UTC. Candles are sorted
chronologically, duplicate timestamps are removed (last candle retained), and
OHLC relationships are validated.

Missing candles are detected and reported in the summary JSON under
`data_quality`. They are never fabricated or inserted into the strategy.

Every base candle is usable only when
`base_open + configured_base_duration <= data_cutoff`. A base candle whose
expected close has merely passed is **not** treated as verified. The final
input candle is excluded whenever its completion cannot be established, and the
excluded rows never reach indicators, signals, HTF aggregation or trade
simulation. The number of excluded candles and their reasons are recorded in
the summary.

Every HTF candle is classified as `COMPLETE`, `INCOMPLETE` or `UNKNOWN`. A
candle is `COMPLETE` only when all of the following hold:

1. its open is aligned with the configured exchange boundary (including
   calendar month starts and Monday-00:00 UTC weeks);
2. its full configured duration ends at or before the verified data cutoff;
3. every underlying base candle in that interval is present.

Only `COMPLETE` candles at or before the base decision time are attached.
Completion is never inferred from the next observed candle or from the mere
existence of an OHLCV row. HTF EMAs are computed only over complete HTF
candles, so an excluded candle cannot influence later lower-timeframe values.
Incomplete or unknown candles are listed in the summary JSON under
`htf_completion`.

Trades whose holding period intersects a missing-candle interval are flagged
with `crosses_data_gap`, `missing_candles_crossed`, `data_gap_intervals` and
`outcome_uncertain`. They remain in the baseline. Separate affected/unaffected
aggregates and a sensitivity view are reported in `metrics` and
`gap_sensitivity`.

## Data cutoff verification (revision 2)

An inferred cutoff is unsafe. In every earlier revision the cutoff was the
expected close of the final base candle
(`last_base_open + timeframe_duration`). Reaching an expected close does not
prove that the candle row was received, finalized or verified. A truncated
download could therefore certify an HTF candle using data that never existed.

The analyzer has two explicitly selected modes.

### Strict mode (default, production research)

Strict mode requires an independently verified cutoff supplied with
`--data-cutoff`. It never invents one. Missing, unparsable, timezone-ambiguous
or out-of-range cutoffs are rejected. A cutoff may not extend beyond the last
supplied base candle's expected close, because a cutoff cannot certify data
that is not present.

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --cutoff-mode strict `
  --data-cutoff "2026-10-27T00:00:00Z"
```

Without `--data-cutoff`, strict mode stops with a clear error and writes no
result files.

### Diagnostic mode (exploratory inspection only)

Diagnostic mode may run without an externally verified cutoff. When no cutoff
is supplied it infers one as the **open** of the final observed base candle, so
the final candle itself is always excluded as unverified. Diagnostic mode also
accepts an explicit `--data-cutoff`, but the run is still marked
`data_cutoff_verified: false`: selecting diagnostic mode means no independent
verification is being asserted. The source remains `explicit` when a cutoff was
supplied, and `inferred_from_final_base_candle_open` otherwise. Every
diagnostic run contains an explicit warning. Diagnostic mode never silently
upgrades itself to verified, and strict mode never silently falls back to
diagnostic mode.

```powershell
python research/strategy_analyzer.py --timeframe 2h --cutoff-mode diagnostic
python research/strategy_analyzer.py --timeframe 2h `
  --cutoff-mode diagnostic --data-cutoff "2026-10-27T00:00:00Z"
```

Diagnostic results are useful for inspecting the engine, but they are not
production-grade. They must be labelled unverified whenever they are shared.

### What "verified" means

`data_cutoff_verified` records the **selected policy**, not an automatic proof
of external data provenance. The software cannot independently audit where a
cutoff came from. In strict mode an explicitly supplied cutoff is treated as
verified on the user's responsibility: the user must establish that the
timestamp is independently sourced and that the underlying data was finalized.
An explicit cutoff is therefore not automatically proof of verification; it is
only accepted as verified in strict mode. Diagnostic mode always reports
`false`, even when a cutoff is supplied explicitly.

| Mode | Source | `data_cutoff_verified` |
|---|---|---|
| strict | explicit | `true` |
| diagnostic | inferred | `false` |
| diagnostic | explicit | `false` |

### Recorded metadata

Every summary JSON records:

| Field | Meaning |
|---|---|
| `data_cutoff` | Cutoff timestamp actually applied |
| `data_cutoff_source` | `explicit` or `inferred_from_final_base_candle_open` |
| `data_cutoff_verified` | `true` only for an explicit cutoff in strict mode |
| `cutoff_mode` | `strict` or `diagnostic` |
| `last_base_candle_timestamp` | Final input candle timestamp |
| `last_base_candle_included` | Whether that candle was used |
| `excluded_incomplete_candles` | Number of excluded base candles |
| `excluded_candle_reasons` | Reasons, with timestamps |
| `last_verified_base_candle` | Last base candle certified complete (`null` in diagnostic mode) |
| `last_verified_htf_candle` | Last HTF candle certified complete |
| `htf_completion_status` | `ALL_HTF_CANDLES_COMPLETE`, `INCOMPLETE_HTF_CANDLES_EXCLUDED` or `NO_COMPLETE_HTF_CANDLES` |
| `data_cutoff_policy` | Full inclusion/completion policy details |

The same provenance fields are included in `metrics`, and the run ID is
sensitive to cutoff timestamp, verification status, mode and the
candle-exclusion/completeness policy.

## Run

Strict mode is the default. Supply a verified cutoff:

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z"
python research/strategy_analyzer.py --timeframe 4h `
  --data-cutoff "2026-10-27T00:00:00Z"
python research/strategy_analyzer.py --timeframe 1d `
  --data-cutoff "2026-10-26T00:00:00Z"
```

Exploratory diagnostic runs (unverified, clearly labelled):

```powershell
python research/strategy_analyzer.py --timeframe 2h --cutoff-mode diagnostic
```

Each timeframe writes into its own directory:

```text
research/results/v42_bugfix_2/2h/
research/results/v42_bugfix_2/4h/
research/results/v42_bugfix_2/1d/
```

The original `research/results/v42/` baseline and the
`research/results/v42_bugfix_1/` revision are retained unchanged.

Per run, the analyzer writes:

- `{tf}_signals.csv` — indicator values, signals and WAIT reasons.
- `{tf}_trades.csv` — one row per simulated trade, including gap-affected
  classification and sizing fields.
- `{tf}_trade_audit.jsonl` — deterministic trade details, complete entry-to-exit
  bar states, stop history and zero-cost breakdown. The exit candle is always
  the final per-bar record.
- `{tf}_summary.json` — run identity, engine/data hashes, configuration,
  execution model, data-quality report, cutoff provenance, HTF completion
  status, warm-up status, metrics and gap sensitivity.
- `{tf}_metrics.csv` — compact metrics table.

Every run has a reproducible `run_id` derived from the engine version, SHA-256
of the actual engine source, SHA-256/versions of the imported execution modules
(numpy/pandas), data-processing version, execution-model settings, execution
constraints, full configuration, timeframe, SHA-256 hashes of the base and HTF
datasets, and the cutoff policy (timestamp, source, verification status, mode,
base-candle inclusion and HTF completion rules). No timestamp or random value
is used. Runs with different cutoff provenance cannot share a run ID. Existing
result files are not overwritten by default. Use `--force` only when you
explicitly want to replace them:

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" --force
```

To keep a separate experiment, use an explicit output directory and/or run ID:

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --output research/results/v42_bugfix_2/2h_experiment_a `
  --run-id ema_v42_2h_experiment_a
```

Optional execution constraints are disabled by default because no verified
BTCUSDT exchange limits were supplied. They can be enabled explicitly:

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --min-quantity 0.00001 --quantity-precision 5 --min-notional 5
```

Rejected entries and their reasons are written to `execution_rejections` in the
summary JSON. The 1x notional cap and risk formula are unchanged.

The cutoff must not extend beyond the last supplied base candle's expected
close. A cutoff beyond the available data is rejected instead of being
silently clamped.

Override input paths if needed:

```powershell
python research/strategy_analyzer.py --timeframe 2h `
  --base "research/data/BTCUSDT/BTCUSDT_2hours.csv" `
  --htf "research/data/BTCUSDT/BTCUSDT_1day.csv"
```

A missing or invalid dataset raises a clear error naming the file or data
issue; the analyzer does not silently fall back to another timeframe.

## Exhaustive combination tester

### Role and integration

`research/v42_exhaustive_combination_tester.py` is a **parameter-search driver**.
For every candidate it calls the real engine:

```python
engine.run_analysis(
    timeframe=timeframe,
    base_path=base_path,
    htf_path=htf_path,
    config_override=candidate,
    output_dir=<temporary directory>,
    run_id=<deterministic id>,
    data_cutoff=<the same cutoff as the analyzer>,
    cutoff_mode=<strict or diagnostic>,
)
```

It does **not** reimplement indicators, signals, sizing, stops, targets, exits,
candle completion or PnL. The analyzer's 2H→1D, 4H→1D and 1D→1W mappings are
used unchanged. Each candidate is written to a temporary output directory so
thousands of `signals/trades/audit` files are not persisted; the metrics and
provenance are retained in the optimization outputs.

The tester maps its public names to analyzer keys explicitly:

| Tester name | Analyzer key(s) |
|---|---|
| `fast_ema` | `fast_ema` |
| `medium_ema` | `medium_ema` |
| `slow_ema` | `slow_ema` |
| `adx_period` | `adx_period` |
| `adx_min` | `adx_min` |
| `atr_period` | `atr_period` |
| `htf_ema` | `htf_ema` |
| `pullback_n` | `pullback_n` |
| `pullback_depth_atr` | `pullback_depth_atr` |
| `trigger_close_location` | `trigger_close_long = t`, `trigger_close_short = 1 - t` |
| `stop_buffer_atr` | `stop_buffer_atr` |
| `min_stop_atr` | `min_stop_atr` |
| `max_stop_atr` | `max_stop_atr` |
| `chandelier_atr` | `chandelier_atr` |
| `time_stop` | `time_stop` |
| target (fixed) | `target_r = 2.0` |

`risk_pct` and every other non-listed parameter keep the frozen per-timeframe
baseline. The target stays at the V4.2 baseline of **2R**.

### Approved ranges

Edit `PARAMETER_RANGES` near the top of
`research/v42_exhaustive_combination_tester.py`. Ranges are inclusive
`[min, max]` with `step`; if the step does not land on `max`, the endpoint is
still included.

| Parameter | Range |
|---|---:|
| Fast EMA | 5–40 |
| Medium EMA | 20–100 |
| Slow EMA | 100–365 (1D capped at 250) |
| ADX period | 7–28 |
| ADX minimum | 15–30 |
| ATR period | 7–28 |
| HTF EMA | 20–100 |
| Pullback lookback | 2–10 |
| Pullback depth | 0–1 ATR |
| Trigger close location | 0.55–0.80 |
| Initial stop buffer | 0.10–1 ATR |
| Minimum stop | 0.25–1 ATR |
| Maximum stop | 1.5–4 ATR |
| Chandelier multiplier | 1.5–5 |
| Time stop | 10–60 candles |

The tester rejects values outside these bounds, non-positive steps, non-integer
steps for integer parameters, any EMA ordering that does not satisfy
`Fast < Medium < Slow`, `min_stop_atr >= max_stop_atr`, invalid trigger
thresholds, and any target other than 2R. For 1D, slow EMA values above 250 are
removed and 250 is included when it falls in the configured range.

### Running searches

Strict cutoff mode is the default. Supply an explicit UTC cutoff for production
research. A diagnostic run may omit it, but every diagnostic result is stored
as **unverified**, even when a cutoff is supplied explicitly.

There is deliberately **no automatic full-grid launch**. `--max-combinations`
caps how many *newly evaluated valid* combinations one invocation will run
(default 20). Completed checkpoint entries are skipped and do not count toward
the cap. The printed Cartesian upper bound is only an upper bound; EMA ordering
and stop constraints remove invalid candidates.

Inspect the plan without running anything (PowerShell):

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" --plan
```

Linux/macOS:

```bash
python research/v42_exhaustive_combination_tester.py --timeframe 2h \
  --data-cutoff "2026-10-27T00:00:00Z" --plan
```

20-combination smoke test (PowerShell):

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --max-combinations 20
```

Linux/macOS:

```bash
python research/v42_exhaustive_combination_tester.py --timeframe 2h \
  --data-cutoff "2026-10-27T00:00:00Z" \
  --max-combinations 20
```

A larger limited search (500 newly evaluated combinations):

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --max-combinations 500
```

Resume that exact search after the cap or an interruption:

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --max-combinations 500 --resume
```

Linux/macOS resume:

```bash
python research/v42_exhaustive_combination_tester.py --timeframe 2h \
  --data-cutoff "2026-10-27T00:00:00Z" \
  --max-combinations 500 --resume
```

Select another timeframe with `--timeframe 4h` or `--timeframe 1d`. Use
`--timeframe all` to run each supported timeframe sequentially.

A literal full-grid run is **not practical**. With the default steps the 2H
Cartesian upper bound is roughly 11.35 trillion combinations before constraint
filtering. If you deliberately want a large bounded run, raise the cap
explicitly and resume until the metadata status becomes `complete`:

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --data-cutoff "2026-10-27T00:00:00Z" `
  --max-combinations 1000000
```

Coarsen the steps first. Keep the checkpoint and do not change ranges, cutoff
mode, cutoff timestamp or datasets between resume invocations: the resume
signature must match exactly.

Diagnostic smoke run without a verified cutoff (clearly unverified):

```powershell
python research/v42_exhaustive_combination_tester.py --timeframe 2h `
  --cutoff-mode diagnostic --max-combinations 20
```

### Search identity, checkpoints and interruption

The `search_id` is a SHA-256 prefix of a deterministic signature containing:

- tester version;
- timeframe;
- full parameter ranges and target values;
- minimum-trade threshold;
- engine source SHA-256;
- base and HTF dataset SHA-256;
- cutoff timestamp, source, verification status and mode.

The same inputs always produce the same `search_id`. Resuming with a different
engine, dataset, cutoff or range set is refused instead of mixing results.
Checkpoints are append-only JSONL files written after every candidate. A normal
Ctrl+C finalises the metadata and preserves completed rows; a hard kill still
leaves the checkpoint and the initial resumable manifest.

Failed combinations are never silently skipped. They are recorded in the
checkpoint, the full results CSV and the failed-combinations CSV with the error
type, message and traceback. Use `--retry-failed` on resume to retry them.

### Outputs

All search outputs live under `research/optimization/` and are separated by
timeframe:

```text
research/optimization/
├── configs/<tf>/<search_id>.json
├── checkpoints/<tf>/<search_id>.jsonl
├── logs/<tf>/<search_id>.log
└── results/<tf>/<search_id>/
    ├── all_results.csv
    ├── top_configs.csv
    ├── failed_combinations.csv
    ├── run_metadata.json
    └── search_config.json
```

| File | Contents |
|---|---|
| `all_results.csv` | One row per evaluated configuration: status, trades, wins/losses, win rate, total gross R, average gross R, profit factor, compounded gross return, max drawdown, long/short counts and expectancy, flattened parameters, `configuration_json`, cutoff provenance, engine/data hashes, gross-only model, run ID and error fields. |
| `top_configs.csv` | Rankable configurations only (`trades >= --min-trades`), sorted by `--rank-by` (default `total_gross_R`, with total R, drawdown and config ID as tie-breakers). Insufficient-trade configurations are excluded. |
| `failed_combinations.csv` | Error rows with type, message and traceback. The header is written even when there are no failures. |
| `run_metadata.json` | Run status (`complete`, `paused_cap_reached`, `interrupted`), counts, search signature, ranges, target values, min-trades, ranking metric, engine/data provenance, cutoff policy, outputs and the top rankable configs. |
| `search_config.json` | Exact search-configuration snapshot used for the run. |
| `configs/<tf>/<search_id>.json` | The same snapshot stored outside the result folder. |
| `checkpoints/<tf>/<search_id>.jsonl` | Append-only resumable checkpoint keyed by `config_id`. |
| `logs/<tf>/<search_id>.log` | Timestamped progress, cap and error messages. |

Every row records `cost_model = EXCLUDED_BY_USER_REQUEST`,
`funding_model = EXCLUDED_BY_USER_REQUEST` and
`market_mode = spot_signal_only`. The tester refuses to pass fee, funding or
slippage keys to the analyzer. SHORT results remain hypothetical/signal-only
for Spot inputs.

### Overfitting and out-of-sample warning

This is a historical parameter search. The best historical combination is
**not** necessarily the best future strategy. A large grid makes it easy to
find configurations that fit noise, especially prefixes biased toward low
values, short samples, or configurations with few trades. The tester excludes
insufficient-trade configurations from the ranking, but that does not make the
remaining results reliable.

Before drawing conclusions:

- pre-register the ranking metric and minimum trade count;
- keep a genuinely untouched out-of-sample period;
- use walk-forward validation rather than selecting on the full history;
- inspect long/short balance, drawdown and trade counts, not only total R;
- treat diagnostic (unverified) runs as exploratory only;
- account for fees, funding and slippage outside this gross-only research
  engine before making any production claim.

## V4.2 logic implemented

- EMA20/EMA50/EMA200 trend alignment.
- Wilder ATR14, ADX14, +DI and -DI.
- Completed higher-timeframe EMA confirmation, using verified completion times
  derived from the configured timeframe duration and an explicit cutoff.
- Previous N-candle pullback, excluding the trigger candle.
- Contemporaneous EMA20 pullback touch and EMA50 ± depth tolerance.
- Trigger candle direction, close location, EMA20 reclaim and previous candle
  high/low break.
- N+1 stop window including the trigger candle.
- Minimum and maximum stop-distance checks at signal and next-open entry.
- Convergence-based warm-up and the 100-bar post-convergence buffer.
- Next-open entry, 2R target from the actual entry, gap-before-intrabar
  stop/target handling, and stop-first same-candle ambiguity.
- Chandelier stop updates after close and activation on the following candle.
- One hypothetical trade at a time per timeframe.
- Independent research equity per experiment and timeframe.
- Quantity, 1x notional cap, risk budget, actual initial risk, `gross_R` and
  `gross_R_budget` accounting. No net fields are produced because funding and
  exchange costs are deliberately excluded.

The frozen parameter table is not modified by the analyzer.

## Tests

From the project root:

```powershell
python -m unittest discover -s research/tests -v
```

The supplied test file covers data parsing, indicators, trigger handling,
stop/target execution ordering, gap fills, risk accounting and warm-up failure
behavior. The integration tests cover the supported timeframe file mappings,
per-timeframe outputs, deterministic run IDs, overwrite protection, timestamp
units, duplicate removal, missing-candle reporting, completed-HTF attachment,
chandelier activation, gap-through-target handling, stop-first ambiguity, JSON
safety, and the absence of funding/fee/slippage fields. The bug-fix regression
suite adds groups A–G: HTF completion across missing candles, all exit paths,
gap-exit MAE/MFE isolation, audit completeness and determinism, run-identity
sensitivity to engine/data/config changes, missing-candle trade classification
and sensitivity reporting, and sizing constraints. `test_cutoff_integrity.py`
adds scenarios A–J for strict-mode rejection, explicit verified cutoffs, final
candle exclusion, diagnostic warnings, incomplete HTF intervals, exact
boundaries, base gaps, calendar weeks/months and leap years, run-ID policy
sensitivity, and no strategy regression on fully verified data.
`test_combination_tester.py` covers inclusive ranges and steps, approved
bounds, integer steps, 1D slow-EMA capping, EMA ordering, stop consistency,
forbidden cost keys, fixed 2R, explicit parameter mapping, deterministic and
duplicate-free generation, real analyzer dispatch, non-mutation of baseline and
candidate configuration, strict/diagnostic cutoff semantics, checkpointing,
resume without repetition, interrupted-run preservation, error logging,
per-timeframe storage, ranking and insufficient-trade exclusion, gross-only
accounting and provenance.

The complete suite currently runs **126 tests**, all passing. Actual executed
result: `Ran 126 tests ... OK`.

## Bug-fix revision 1

Confirmed defects corrected in this revision:

1. HTF completion was inferred from the next observed candle, creating
   lookahead across base-data gaps. It is now derived from the configured
   timeframe duration. This affected one 2H and one 4H base candle
   (2018-02-08 00:00 UTC); no signal or trade outcome changed on the supplied
   datasets because the HTF filter result at that candle was unchanged.
2. The exit candle was appended to the audit only after exit checks, so
   completed trades could lack their exit bar. Every exit path now records the
   exit candle before breaking.
3. Gap exits updated MAE/MFE from the full candle before filling at the open.
   Post-exit highs/lows are now excluded for gap stops and gap targets.
4. Run identity omitted the engine source and imported execution stack. It now
   includes both.
5. Final HTF completion was inferred from the median interval. It now uses the
   configured exchange timeframe duration and an explicit/derived cutoff, with
   COMPLETE/INCOMPLETE/UNKNOWN reporting.
6. Missing-candle-affected trades were not identified. They are now classified
   and reported without being removed from the baseline.

The original V4.2 baseline in `research/results/v42/` is unchanged. The
corrected run is in `research/results/v42_bugfix_1/`, with a comparison in
`research/results/v42_bugfix_1/BASELINE_COMPARISON.md`.

## Bug-fix revision 2

Revision 1 still derived a cutoff from the expected close of the final base
candle. That is not proof that the row was received or finalized. Revision 2:

1. Makes strict mode the default and requires an explicit `--data-cutoff`.
2. Rejects missing, invalid, timezone-unsafe or beyond-availability cutoffs.
3. Adds an explicitly selected diagnostic mode whose inferred cutoff is the
   final base candle **open**, with the final candle excluded.
4. Excludes every base candle not certified complete before the cutoff from
   indicators, signals, HTF aggregation and trades.
5. Requires full underlying base coverage before certifying an HTF candle, and
   computes HTF EMAs only over complete HTF candles.
6. Records cutoff provenance and completeness metadata in every summary and in
   the run identity.
7. Supports 2H, 4H, 1D, 1W and calendar 1M boundaries, including month-end,
   leap-year February, year-end and UTC normalization.
8. Reports `data_cutoff_verified: true` only for an explicit cutoff in strict
   mode. Diagnostic mode always reports `false`, including when an explicit
   cutoff is supplied.

On the supplied datasets no independent cutoff metadata exists, so
`research/results/v42_bugfix_2/` was produced in diagnostic mode and is
explicitly unverified. The comparison in
`research/results/v42_bugfix_2/BASELINE_COMPARISON.md` records exactly which
results changed and why.

## Limitations and explicit distinctions

1. The engine implements the frozen V4.2 signal and execution rules. It does
   not implement a V1 comparison, because V4.2 requires an immutable V1
   reference file/hash that has not been supplied.
2. Funding and fee/slippage models are intentionally excluded.
3. No liquidation model is included; the default is 1x with a notional cap.
4. The V4.2 optimizer acceptance protocol (bootstrap, plateau, untouched OOS,
   DSR and multiple-testing controls) is not run by this single-configuration
   analyzer.
5. Zero-range bars remain valid for indicators and pullback checks but are
   invalid trigger candles.
6. The convergence check is explicit and may return `NO_DATA` if the required
   alternate initialization cannot converge before data exhaustion. Warm-up is
   not shortened to force a result.
7. Base datasets may contain exchange gaps. They are reported but not filled,
   because the engine must never fabricate missing candles or prices. Trades
   spanning those intervals are flagged as uncertain because the intragap
   stop/target path cannot be verified.
8. HTF candles are excluded unless they are boundary-aligned, fully elapsed at
   or before the verified cutoff, and fully covered by base candles. Their
   status is `INCOMPLETE` or `UNKNOWN` and they cannot leak into lower
   timeframes. Without an independently verified cutoff, only diagnostic mode
   is available and its results are unverified.
9. No frozen V4.2 strategy specification document was found in the project.
   The implemented EMA hierarchy and directional DI filters were inspected and
   left unchanged, but exact specification parity cannot be certified.
10. Minimum quantity, quantity precision and minimum notional are configurable
    execution constraints, disabled by default. No BTCUSDT-specific exchange
    limits were invented or asserted.
11. Intrabar MAE/MFE use the binding exit price plus completed prior bars.
    Same-bar opposite-side extremes are not counted because intrabar ordering
    is unobservable; this avoids post-exit contamination but can understate
    within-bar excursions. Gap exits are handled explicitly.
12. The supplied BTCUSDT datasets contain no independent completion metadata,
    so the checked-in `v42_bugfix_2` results are diagnostic and not
    production-grade. A production run requires an externally verified cutoff.

## No broker connectivity

This is a local research and analysis tool. It does not place orders or connect
to an exchange account.
