# V4.2 Baseline Comparison — Bug-Fix Revision 2

Original run: `research/results/v42/`
Revision 1 run: `research/results/v42_bugfix_1/`
Revision 2 run: `research/results/v42_bugfix_2/`

All figures are **gross** (fees, slippage and funding remain excluded by user
request). No strategy parameter, entry/exit rule, warm-up rule or sizing formula
was changed in this revision.

**Revision 2 results are diagnostic and unverified.** The supplied BTCUSDT
datasets contain no independent cutoff/completion metadata, so an externally
verified cutoff could not be established. The run used
`--cutoff-mode diagnostic`; the inferred cutoff is the open of the final
observed base candle, and that candle was excluded. These results are suitable
for regression inspection, not for production research claims.

## Run identity

| Timeframe | V4.2 | Revision 1 | Revision 2 | Revision 2 cutoff |
|---|---|---|---|---|
| 2H | `31af82caf96618ad` | `6f9d149c2ea8b7df` | `b6c6995a767a8d3a` | 2026-10-27 02:00 UTC (inferred) |
| 4H | `1c930139ab9ec496` | `6d4b81e4bfcb3546` | `776c11eeecfc8d3d` | 2026-10-27 00:00 UTC (inferred) |
| 1D | `3b0ef355d3011a5f` | `7f338e8cb4d04b38` | `ea6c9f3cbc060bfb` | 2026-10-26 00:00 UTC (inferred) |

Revision 2 engine SHA-256:
`2ccc3c497ff0d608293392114af7a23c714fee661163bd8d14f7ee642a57e676`

Run IDs differ from revision 1 because the identity now includes the cutoff
policy (timestamp, source, verification flag, mode, base-candle inclusion rule
and HTF completion rule) in addition to the engine source hash, imported
execution stack, data-processing version, configuration,
execution model/constraints and dataset hashes.

## 2H

| Metric | V4.2 | Revision 1 | Revision 2 | R2 vs R1 |
|---|---:|---:|---:|---:|
| Trades | 290 | 290 | 290 | 0 |
| Win rate | 40.00% | 40.00% | 40.00% | 0.00 pp |
| Profit factor (gross) | 1.2179 | 1.2179 | 1.2160 | −0.0019 |
| Average gross R | 0.1099 | 0.1099 | 0.1090 | −0.0009 |
| Total gross R | 31.8758 | 31.8758 | 31.6010 | −0.2748 |
| Compounded gross return | 16.7275% | 16.7275% | 16.5674% | −0.1601 pp |
| Maximum drawdown | −7.1580% | −7.1580% | −7.1580% | 0.0000 pp |
| LONG expectancy | 0.1370 R | 0.1370 R | 0.1370 R | 0.0000 R |
| SHORT expectancy | 0.0873 R | 0.0873 R | 0.0856 R | −0.0017 R |
| Gap-affected trades | 3\* | 3 | 3 | 0 |

Two 2H outcomes changed, both traceable to the cutoff policy:

1. **Final candle exclusion.** The last base candle
   (2026-10-27 02:00 UTC) is unverified and was excluded. The open trade
   `trade_id 290` previously exited `DATA_END` at 2026-10-27 02:00 with
   `gross_R = +0.3651`; it now exits at 2026-10-27 00:00 with
   `gross_R = +0.0903`. This accounts for the entire −0.2748 R change in total
   gross R.
2. **Incomplete daily HTF exclusion.** One 2H candle
   (2021-04-20 02:00 UTC) is missing from the raw dataset. Consequently the
   2021-04-20 daily candle is `INCOMPLETE`
   (`underlying_base_candles_missing_or_incomplete`) and is no longer attached.
   HTF bias at 2021-04-21 02:00 therefore differs from revision 1, producing a
   SHORT signal at 2021-04-21 02:00 (entry 04:00) instead of 2021-04-22 16:00
   (entry 18:00). Both trades return exactly +2R, so the swap changes the
   entry/exit dates but not the total R from that episode. HTF EMA values also
   shift slightly because they are now computed only over complete HTF candles.

Twenty daily candles are excluded in total (the raw 2H data has 53 missing
candles across 18 gap events). Each exclusion is recorded in
`2h_summary.json → htf_completion.excluded_candles`.

## 4H

| Metric | V4.2 | Revision 1 | Revision 2 | R2 vs R1 |
|---|---:|---:|---:|---:|
| Trades | 207 | 207 | 207 | 0 |
| Win rate | 33.33% | 33.33% | 33.33% | 0.00 pp |
| Profit factor (gross) | 0.9324 | 0.9324 | 0.9324 | 0.0000 |
| Average gross R | −0.0337 | −0.0337 | −0.0337 | 0.0000 |
| Total gross R | −6.9664 | −6.9664 | −6.9664 | 0.0000 |
| Compounded gross return | −5.7058% | −5.7058% | −5.7058% | 0.0000 pp |
| Maximum drawdown | −13.2581% | −13.2581% | −13.2581% | 0.0000 pp |
| LONG expectancy | 0.2163 R | 0.2163 R | 0.2163 R | 0.0000 R |
| SHORT expectancy | −0.2584 R | −0.2584 R | −0.2584 R | 0.0000 R |
| Gap-affected trades | 1\* | 1 | 1 | 0 |

The final base candle (2026-10-27 00:00 UTC) was excluded, but the last trade
closed on 2026-10-07, so no outcome changed. Ten daily HTF candles are excluded
for missing underlying base coverage; none of them altered an attached bias at
a decision that produced a trade. All 207 trade rows are identical to revision
1 apart from the run ID.

## 1D

| Metric | V4.2 | Revision 1 | Revision 2 | R2 vs R1 |
|---|---:|---:|---:|---:|
| Trades | 25 | 25 | 25 | 0 |
| Win rate | 20.00% | 20.00% | 20.00% | 0.00 pp |
| Profit factor (gross) | 0.6180 | 0.6180 | 0.6180 | 0.0000 |
| Average gross R | −0.2472 | −0.2472 | −0.2472 | 0.0000 |
| Total gross R | −6.1809 | −6.1809 | −6.1809 | 0.0000 |
| Compounded gross return | −6.1545% | −6.1545% | −6.1545% | 0.0000 pp |
| Maximum drawdown | −8.4861% | −8.4861% | −8.4861% | 0.0000 pp |
| LONG expectancy | −0.5079 R | −0.5079 R | −0.5079 R | 0.0000 R |
| SHORT expectancy | −0.0066 R | −0.0066 R | −0.0066 R | 0.0000 R |
| Gap-affected trades | 0\* | 0 | 0 | 0 |

The final base candle (2026-10-26 00:00 UTC) and the final weekly HTF candle
(2026-10-19 00:00 UTC) were excluded, but the last trade closed on
2026-10-15. All 25 trade rows are identical to revision 1 apart from the run ID.

\* Original V4.2 did not report gap-affected trades; the value was recomputed
ex post for comparison. No original result file was modified.

## What did not change

- EMA periods, EMA hierarchy, ADX/DI filters, HTF bias rule.
- Pullback, trigger, stop and target rules; 2R target; chandelier and time stop.
- Position sizing, 1x notional cap and trade sequencing.
- Gross PnL/R calculations and execution assumptions.
- Warm-up: `CONVERGENCE_PASSED` for all three timeframes in both revisions.

The only result changes are traceable to data excluded by the stricter cutoff
policy, not to altered strategy logic.

## Verification of preserved baselines

`research/results/v42/` and `research/results/v42_bugfix_1/` were not written to
during this revision. Revision 2 wrote only under
`research/results/v42_bugfix_2/`.
