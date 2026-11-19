# V4.2 optimization outputs

This directory is written only by
`research/v42_exhaustive_combination_tester.py`. It is deliberately separate
from the frozen historical results in `research/results/`.

Nothing here is produced automatically. Each invocation evaluates at most
`--max-combinations` newly valid combinations and can be resumed.

## Layout

```text
optimization/
├── configs/
│   └── <timeframe>/
│       └── <search_id>.json
├── checkpoints/
│   └── <timeframe>/
│       └── <search_id>.jsonl
├── logs/
│   └── <timeframe>/
│       └── <search_id>.log
└── results/
    └── <timeframe>/
        └── <search_id>/
            ├── all_results.csv
            ├── top_configs.csv
            ├── failed_combinations.csv
            ├── run_metadata.json
            └── search_config.json
```

`<timeframe>` is `2h`, `4h` or `1d`. `<search_id>` is the first 16 hex
characters of the deterministic search signature. A different engine hash,
dataset hash, cutoff provenance, range set, target value or minimum-trade
threshold creates a different directory instead of mixing results.

## File meanings

- `all_results.csv` — every evaluated configuration, including errors and
  configurations with too few trades. Parameter columns are flattened; the
  canonical analyzer configuration is in `configuration_json`.
- `top_configs.csv` — rankable configurations only
  (`trades >= --min-trades`), ordered by `--rank-by` (default
  `total_gross_R`).
- `failed_combinations.csv` — error rows with traceback. Header-only when no
  combination failed.
- `run_metadata.json` — status, counts, signature, engine/data provenance,
  cutoff policy, ranges, target values, ranking settings, output paths and the
  best rankable configurations.
- `search_config.json` and `configs/<tf>/<search_id>.json` — exact search
  configuration snapshot.
- `checkpoints/<tf>/<search_id>.jsonl` — append-only resumable checkpoint.
- `logs/<tf>/<search_id>.log` — progress and error log.

## Accounting

All results are gross-only. Fees, funding and slippage are excluded by the
analyzer. SHORT results are hypothetical/signal-only for Spot inputs. Do not
describe these outputs as net performance.

## Status values

| Status | Meaning |
|---|---|
| `complete` | The generator was exhausted for this search signature. |
| `paused_cap_reached` | The per-invocation cap was reached; use `--resume`. |
| `interrupted` | Ctrl+C or an interruption stopped the loop; completed rows are preserved. |
| `running` | Written before candidate execution; a hard-killed run leaves this state and can still be resumed. |

## Commands

See the "Exhaustive combination tester" section of `research/README.md` for
PowerShell and Linux/macOS commands.
