# Bug-Fix Revision 2 — Data Cutoff Verification

Engine: `research/strategy_analyzer.py`
Engine SHA-256 at result generation:
`2ccc3c497ff0d608293392114af7a23c714fee661163bd8d14f7ee642a57e676`
Final engine SHA-256 after the verification-status correction:
`11d52caaff72ddae3fa197db23f6816ee21e0e5fc489de6be42031e30a464f13`

Data-processing version: `V4.2-bugfix2`

## Root cause

`derive_data_cutoff()` returned:

```python
return base_index[-1] + timeframe_interval(timeframe), "derived_from_last_base_candle_close"
```

The engine treated the **expected closing timestamp** of the final base candle
as proof that the candle had been received and finalized. A partially
downloaded dataset, a still-forming final candle, or a truncated export would
therefore be certified as complete. That value then authorized higher-timeframe
(HTF) candles and could influence signals and trades using data that was never
verified.

Revision 2 removes that inference entirely.

## Exact code changes

All changes are confined to cutoff resolution, candle eligibility, HTF
completion, provenance metadata, run identity and CLI reporting. No strategy
rule was edited.

1. **Cutoff modes.** Added `CUTOFF_MODE_STRICT` (`strict`, default) and
   `CUTOFF_MODE_DIAGNOSTIC` (`diagnostic`), plus `validate_cutoff_mode()`.
2. **`resolve_data_cutoff()`** replaces inference as the single source of truth:
   - Strict mode requires an explicit cutoff and raises a clear `ValueError`
     when it is missing.
   - Invalid/NaT/non-parseable values are rejected.
   - A cutoff beyond the last supplied candle's expected close is rejected.
   - Diagnostic mode infers the cutoff as the final observed candle's **open**,
     marks it unverified and excludes that final candle.
   - A candle is included only when
     `open + configured_duration <= cutoff`.
   - Records excluded count, timestamps and reasons.
3. **`derive_data_cutoff()`** is retained as a compatibility wrapper returning
   `(cutoff, source)` and delegates to `resolve_data_cutoff()`.
4. **`htf_period_end()` and calendar support.** Fixed-duration timeframes add
   the configured duration; `1m` uses `pd.offsets.MonthBegin(1)`. Added
   `CALENDAR_TIMEFRAMES`, `timeframe_duration_label()` and month-boundary
   alignment in `exchange_boundary_aligned()`.
5. **Base-coverage verification.** Added `required_base_opens()` and
   `base_coverage_for_htf()`. `htf_completion_frame()` now requires:
   boundary alignment, full duration elapsed at/before the cutoff, and every
   expected base candle present. Any missing base candle yields `INCOMPLETE`
   with `underlying_base_candles_missing_or_incomplete`.
6. **`attach_htf_indicators()`** attaches only `COMPLETE` candles, computes the
   HTF EMA only over complete candles, masks attachments for base rows closing
   after the cutoff, and passes cutoff provenance into the completion report.
7. **`indicator_snapshot()`, `check_convergence()`, `build_signals()`** thread
   the cutoff mode through and refuse to evaluate base rows beyond the cutoff.
   They also accept the already-resolved cutoff policy from `run_analysis()`,
   so a verified cutoff that falls between candle closes is not misread as
   extending beyond the truncated frame.
8. **`run_analysis()`** resolves the cutoff before any indicator work,
   truncates base candles to verified rows, runs HTF completion on the
   truncated base, and writes all provenance/completeness metadata.
9. **`compute_run_id()`** now includes a `cutoff_policy` block: mode, timestamp,
   source, verified flag, base inclusion rule, incomplete-candle policy, HTF
   completion rule and completion basis.
10. **CLI** adds `--cutoff-mode {strict,diagnostic}` (default `strict`), a
    mode banner, cutoff provenance output and a loud diagnostic warning.
11. `DATA_PROCESSING_VERSION` is `V4.2-bugfix2`; default output root is
    `research/results/v42_bugfix_2`.

No changes were made to EMA periods/calculations, EMA hierarchy, ADX/DI,
pullback/entry/confirmation conditions, ATR/stops, 2R target, chandelier,
time stop, sizing, 1x cap, simulation ordering or gross PnL.

## Files modified

- `research/strategy_analyzer.py`
- `research/tests/test_bugfix_regressions.py` (existing tests adapted to
  explicit cutoffs and full base coverage; no assertion was weakened)
- `research/tests/test_integration_v42.py` (explicit cutoffs added)
- `research/tests/test_cutoff_integrity.py` (new A–J suite)
- `research/README.md`
- `research/results/v42_bugfix_2/` (new results and reports)
- `research/FILE_HASHES.json`

Preserved unchanged: `research/results/v42/`,
`research/results/v42_bugfix_1/`, `research/data/BTCUSDT/`,
`research/tests/test_strategy_analyzer.py`.

## Tests added (A–J)

`research/tests/test_cutoff_integrity.py` contains 38 tests:

- **A. Strict mode without cutoff** — CLI/API raises a clear error, no summary
  is written, no silent inference.
- **B. Explicit verified cutoff** — accepted, marked verified, only eligible
  candles reach signals, metadata persisted.
- **C. Partially completed final base candle** — excluded; a synthetic
  out-of-range final candle does not affect signals/trades; results match a
  physically trimmed dataset.
- **D. Diagnostic inferred cutoff** — marked unverified, final candle excluded,
  explicit warning recorded.
- **E. Incomplete HTF candle** — missing base coverage yields `INCOMPLETE` and
  is not attached; unaligned opens yield `UNKNOWN`.
- **F. Exact boundaries** — candle ending exactly at the cutoff is included;
  one second after is excluded; a cutoff falling between candle closes is
  accepted; HTF completion respects the documented convention.
- **G. Missing base candles** — affected HTF intervals are not certified;
  existing gap reporting is preserved.
- **H. Calendar boundaries** — month-end, leap-year February (29 required base
  days), year-end, weekly Monday-00:00 alignment, UTC normalization of
  non-UTC cutoffs.
- **I. Run-ID integrity** — different cutoff timestamps, verified vs inferred
  policies and strict vs diagnostic modes all produce different IDs.
- **J. No strategy regression** — on fully verified synthetic data, indicator
  values, signals, WAIT reasons, trades, total gross R and drawdown are
  identical across policy modes.
- **Verification-status consistency (5 tests)** — strict + explicit is
  verified; diagnostic + inferred is unverified; diagnostic + explicit is
  unverified while the source remains `explicit`; summary, metrics CSV, metrics
  object, HTF completion report, policy block and run identity all agree; the
  verified flag alone changes the run ID.

## Test execution results

Command:

```powershell
.venv\Scripts\python.exe -m unittest discover -s research/tests
```

Actual result:

```text
Ran 98 tests in 14.140s
OK
```

Per-file counts: `test_strategy_analyzer.py` 7,
`test_integration_v42.py` 13, `test_bugfix_regressions.py` 40,
`test_cutoff_integrity.py` 38. All 60 previously passing tests still pass.

Static check: `.venv\Scripts\python.exe -m py_compile research\strategy_analyzer.py`
completed without errors.

## Cutoff verification behavior

| Situation | Result |
|---|---|
| Strict mode, no cutoff | `ValueError`, no output written |
| Strict mode, invalid/NaT cutoff | `ValueError` |
| Strict mode, cutoff beyond data | `ValueError` |
| Strict mode, valid cutoff | accepted, `data_cutoff_verified: true` |
| Diagnostic mode, no cutoff | inferred from final candle open, `verified: false`, warning |
| Diagnostic mode, explicit cutoff | accepted, still `verified: false` (mode is diagnostic) |
| Cutoff between candle closes | accepted; only candles closing at/before it are used |
| Candle closes after cutoff | excluded, reason recorded |
| HTF interval missing a base candle | `INCOMPLETE`, not attached |
| HTF open not boundary-aligned | `UNKNOWN`, not attached |

`data_cutoff_verified` reflects the selected policy, not an automatic proof of
external provenance. Strict mode treats an explicitly supplied cutoff as
verified on the user's responsibility to establish independent provenance;
diagnostic mode always reports `false`, even when the cutoff is explicit. The
source string still distinguishes `explicit` from
`inferred_from_final_base_candle_open`.

This metadata correction changed no cutoff timestamps, candle selection, HTF
completion, signals, trades or PnL. The historical outputs in
`research/results/v42_bugfix_2/` were **not** regenerated: they were produced
in diagnostic mode without an explicit cutoff, so their recorded status was
already `data_cutoff_verified: false`.

Every summary records `data_cutoff`, `data_cutoff_source`,
`data_cutoff_verified`, `cutoff_mode`, `last_base_candle_timestamp`,
`last_base_candle_included`, `excluded_incomplete_candles`,
`excluded_candle_reasons`, `last_verified_base_candle`,
`last_verified_htf_candle`, `htf_completion_status` and the full
`data_cutoff_policy`. The same provenance is included in `metrics` and in the
run identity.

## Historical baseline comparison

The supplied datasets contain no independent cutoff/finality metadata, so a
strict production regeneration was impossible. `research/results/v42_bugfix_2/`
was regenerated from the raw candles in **diagnostic mode** and is explicitly
unverified.

| Timeframe | V4.2 total gross R | R1 total gross R | R2 total gross R | R2 trades | R2 DD |
|---|---:|---:|---:|---:|---:|
| 2H | 31.8758 | 31.8758 | 31.6010 | 290 | −7.1580% |
| 4H | −6.9664 | −6.9664 | −6.9664 | 207 | −13.2581% |
| 1D | −6.1809 | −6.1809 | −6.1809 | 25 | −8.4861% |

Only 2H changed:

1. The final 2H candle was excluded, moving the open trade's `DATA_END` exit
   from 2026-10-27 02:00 (+0.3651 R) to 2026-10-27 00:00 (+0.0903 R), a
   −0.2748 R change.
2. A missing 2H candle at 2021-04-20 02:00 makes the 2021-04-20 daily
   `INCOMPLETE`. The resulting HTF bias change moved one SHORT entry from
   2021-04-22 18:00 to 2021-04-21 04:00; both returned +2R, so the episode's
   contribution did not change.

4H and 1D trade sets are identical to revision 1 apart from run IDs. Full
details are in `research/results/v42_bugfix_2/BASELINE_COMPARISON.md`.

## Remaining limitations

1. No independently verified cutoff exists for the supplied BTCUSDT datasets,
   so checked-in revision 2 results are diagnostic, not production-grade.
2. Base-coverage HTF verification is conservative: any missing base candle
   inside an HTF interval excludes that HTF candle, even when the separately
   supplied HTF file appears complete. This reduced usable HTF history
   slightly (2H: 20 daily candles; 4H: 10; 1D: 1 weekly).
3. No frozen V4.2 specification document exists; exact specification parity
   remains uncertified.
4. The engine remains OHLCV-only with fee/funding/slippage excluded by request.
5. Historical regeneration was performed from the raw candle files present in
   this repository; it was not possible to obtain an external completion
   authority to certify the end of those files.
