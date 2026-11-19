# Optimization artifacts

The search driver owns this output tree. See [the research README](../README.md)
for ranges, process architecture, cutoff requirements, commands, ranking and recovery.

Existing v1 results and JSONL checkpoints are historical artifacts. They are retained
unchanged and cannot be resumed with a different engine/source signature.

New v2 runs use `results/<timeframe>/<search-id>/records/<prefix>/<config-id>.json`
as their authoritative atomic recovery store. `checkpoint.json` is a periodic
summary; `all_results.csv`, `top_configs.csv`, `failed_combinations.csv` and the
external JSONL checkpoint are derived exports. Every failed attempt also has an
immutable file under the run's `failures/` directory. Workers never write here.
