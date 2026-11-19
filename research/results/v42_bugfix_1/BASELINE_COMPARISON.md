# V4.2 Baseline Comparison — Bug-Fix Revision 1

Original run: `research/results/v42/`
Corrected run: `research/results/v42_bugfix_1/`

All figures are **gross** (fees, slippage and funding remain excluded by user
request). No strategy parameter, entry/exit rule, warm-up rule or sizing formula
was changed in this revision.

## Run identity

| Timeframe | Original run ID | Corrected run ID | Corrected engine SHA-256 |
|---|---|---|---|
| 2H | `31af82caf96618ad` | `6f9d149c2ea8b7df` | `d7e5a5ae03ed09a6972d4cfe8c7f0efacb14be4b3f549c25e02fa2326756c5c2` |
| 4H | `1c930139ab9ec496` | `6d4b81e4bfcb3546` | `d7e5a5ae03ed09a6972d4cfe8c7f0efacb14be4b3f549c25e02fa2326756c5c2` |
| 1D | `3b0ef355d3011a5f` | `7f338e8cb4d04b38` | `d7e5a5ae03ed09a6972d4cfe8c7f0efacb14be4b3f549c25e02fa2326756c5c2` |

The corrected run ID changes because the identity now includes the engine source
hash, imported execution-module fingerprints, data-processing version,
execution-model settings and execution constraints, in addition to the previous
version/configuration/dataset hashes.

## 2H

| Metric | Original V4.2 | Corrected V4.2 | Difference |
|---|---:|---:|---:|
| Trades | 290 | 290 | 0 |
| Win rate | 40.00% | 40.00% | 0.00 pp |
| Profit factor | 1.2179 | 1.2179 | 0.0000 |
| Average gross R | 0.1099 | 0.1099 | 0.0000 |
| Total gross R | 31.8758 | 31.8758 | 0.0000 |
| Compounded gross return | 16.7275% | 16.7275% | 0.0000 pp |
| Maximum drawdown | −7.1580% | −7.1580% | 0.0000 pp |
| LONG expectancy | 0.1370 R | 0.1370 R | 0.0000 R |
| SHORT expectancy | 0.0873 R | 0.0873 R | 0.0000 R |
| Gap-affected trades | 3\* | 3 | 0 |

## 4H

| Metric | Original V4.2 | Corrected V4.2 | Difference |
|---|---:|---:|---:|
| Trades | 207 | 207 | 0 |
| Win rate | 33.33% | 33.33% | 0.00 pp |
| Profit factor | 0.9324 | 0.9324 | 0.0000 |
| Average gross R | −0.0337 | −0.0337 | 0.0000 |
| Total gross R | −6.9664 | −6.9664 | 0.0000 |
| Compounded gross return | −5.7058% | −5.7058% | 0.0000 pp |
| Maximum drawdown | −13.2581% | −13.2581% | 0.0000 pp |
| LONG expectancy | 0.2163 R | 0.2163 R | 0.0000 R |
| SHORT expectancy | −0.2584 R | −0.2584 R | 0.0000 R |
| Gap-affected trades | 1\* | 1 | 0 |

## 1D

| Metric | Original V4.2 | Corrected V4.2 | Difference |
|---|---:|---:|---:|
| Trades | 25 | 25 | 0 |
| Win rate | 20.00% | 20.00% | 0.00 pp |
| Profit factor | 0.6180 | 0.6180 | 0.0000 |
| Average gross R | −0.2472 | −0.2472 | 0.0000 |
| Total gross R | −6.1809 | −6.1809 | 0.0000 |
| Compounded gross return | −6.1545% | −6.1545% | 0.0000 pp |
| Maximum drawdown | −8.4861% | −8.4861% | 0.0000 pp |
| LONG expectancy | −0.5079 R | −0.5079 R | 0.0000 R |
| SHORT expectancy | −0.0066 R | −0.0066 R | 0.0000 R |
| Gap-affected trades | 0\* | 0 | 0 |

\* The original engine did not report gap-affected trades. The original count was
recomputed ex post from the original trade entry/exit times and the same
missing-candle intervals, purely for comparison. No original result file was
modified.

## Why the trade results are unchanged

The higher-timeframe completion fix changed exactly one attached HTF value in
each of 2H and 4H:

| Timeframe | Base candle | Original attached daily close | Corrected attached daily close |
|---|---|---|---|
| 2H | 2018-02-08 00:00 UTC | 7784.02 (2018-02-08 daily) | 7599.00 (2018-02-07 daily) |
| 4H | 2018-02-08 00:00 UTC | 7784.02 (2018-02-08 daily) | 7599.00 (2018-02-07 daily) |
| 1D | — | — | no differing attachment |

The corrected value is the daily candle that had actually completed by the base
candle's real close (02:00 UTC for 2H, 04:00 UTC for 4H). The original engine
extended the 2018-02-08 00:00 base candle to the next observed candle on
2018-02-09 10:00, which allowed the 2018-02-08 daily close to leak backwards.

An independent old-vs-new comparison confirmed:

- 2H: 1 differing HTF attachment, 0 signal differences, 0 WAIT-reason
  differences, 0 trade-outcome differences.
- 4H: 1 differing HTF attachment, 0 signal differences, 0 WAIT-reason
  differences, 0 trade-outcome differences.
- 1D: 0 differing HTF attachments, 0 signal/WAIT/trade differences.

The lookahead was real and is now eliminated, but on these datasets it did not
change the HTF filter outcome at that candle, so the historical trade list is
unchanged. Inputs are read directly from a configured duration and explicit
cutoff; completion is no longer inferred from the next observed candle.

## Audit completeness

| Timeframe | Old audit rows | Old empty per-bar | Old final bar ≠ exit | New empty per-bar | New final bar ≠ exit |
|---|---:|---:|---:|---:|---:|
| 2H | 290 | 9 | 261 | 0 | 0 |
| 4H | 207 | 4 | 187 | 0 | 0 |
| 1D | 25 | 1 | 24 | 0 | 0 |

Every corrected trade now has a complete entry-to-exit trace. The final per-bar
record is the exit candle and carries the exit reason, fill and timestamp.

## MAE/MFE correction

Gap exits now stop accumulating excursions at the actual open/limit fill. The
number of changed MAE/MFE values versus the original is:

| Timeframe | MAE values changed | MFE values changed |
|---|---:|---:|
| 2H | 173 | 93 |
| 4H | 128 | 52 |
| 1D | 17 | 6 |

These are diagnostic fields only. Trade outcomes and PnL do not depend on them,
so the performance tables above are unchanged. Post-exit highs/lows are excluded
on gap exits. For intrabar exits, the binding exit price is used and same-bar
opposite-side extremes are not counted when the event order is unobservable.

## Missing-candle-affected trades

| Timeframe | Total | Gap-affected | Unaffected | Affected gross R | Unaffected gross R | Affected compounded | Unaffected compounded |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2H | 290 | 3 | 287 | −1.5417 R | +33.4175 R | −0.7691% | +17.6322% |
| 4H | 207 | 1 | 206 | −1.0000 R | −5.9664 R | −0.7500% | −4.9933% |
| 1D | 25 | 0 | 25 | 0.0000 R | −6.1809 R | 0.0000% | −6.1545% |

Affected trades remain in the baseline and in all headline metrics. All three
2H-affected trades and the one 4H-affected trade are flagged
`outcome_uncertain = true` because a stop or target could have been touched
inside the missing interval. The sensitivity figures are a separate view, not a
replacement baseline. Subset compounded returns are multiplicative contributions
using each trade's recorded `equity_before`; they are not independent
re-simulations.

## Final HTF candle verification

| Timeframe | HTF | Data cutoff | Complete | Incomplete | Unknown | Excluded |
|---|---|---|---:|---:|---:|---:|
| 2H | 1D | 2026-10-27 04:00 UTC | 3358 | 0 | 0 | 0 |
| 4H | 1D | 2026-10-27 04:00 UTC | 3358 | 0 | 0 | 0 |
| 1D | 1W | 2026-10-27 00:00 UTC | 480 | 0 | 0 | 0 |

The cutoffs are derived from the final base candle's configured close. No final
HTF candle needed exclusion on these datasets. The engine still excludes any
candle whose configured completion is after the cutoff, and any candle whose
open is not aligned to the expected exchange boundary is classified `UNKNOWN`
and excluded. Synthetic tests cover both cases.

## Specification parity and sizing constraints

No frozen V4.2 specification document was found in the project. The implemented
EMA hierarchy (`ema_fast > ema_mid`, SHORT mirror) and directional DI filters
(`plus_di > minus_di`, SHORT mirror) were inspected and left unchanged, but
exact parity cannot be certified. No requirement was invented.

Minimum quantity, quantity precision and minimum notional are implemented as
optional execution constraints and are disabled by default. No BTCUSDT-specific
exchange limits were invented. The 1x notional cap, risk percentage and sizing
formula are unchanged.
