# Backup, storage and database maintenance

This document describes the portable backup system, the data classification it
relies on, and the safe SQLite maintenance performed on the live database.

## 1. Data classification

| Class | Meaning | Tables | Backup? |
| --- | --- | --- | --- |
| **A — essential user data** | Cannot be regenerated from providers | `instruments`, `instrument_aliases`, `watchlist`, `holding_transactions`, `signal_audit`, `catalogue_meta` | **Yes**, compressed and Git-tracked |
| **B — regenerable data** | Rebuilt from TradingView or local pipelines | `market_bars`, `market_analytics_snapshots`, `strategy_snapshots`, `analytics_jobs`, `news_articles`, `news_article_symbols`, `news_symbol_cache`, `quote_snapshots` | No |
| **C — temporary data** | Local-only runtime artefacts | WAL/SHM/journal files, logs, partial writes, lock files, local full-DB snapshots, exports, `node_modules`, research datasets | No |

There is no SQLite table for application preferences. Operational settings live
in `.env` (excluded because it can contain secrets) and browser-managed UI
preferences live in `localStorage`; neither is part of the financial database.

### Live record counts at migration time

| Table | Rows |
| --- | ---: |
| `market_bars` | 1,641,300 |
| `market_analytics_snapshots` | 274 |
| `strategy_snapshots` | 2,232 |
| `analytics_jobs` | 2,132 |
| `news_articles` | 1,182 |
| `news_article_symbols` | 1,385 |
| `signal_audit` | 1,252 |
| `instruments` | 336 |
| `instrument_aliases` | 189 |
| `watchlist` | 15 |
| `holding_transactions` | 3 |
| `catalogue_meta` | 3 |

## 2. Portable backup format

Each snapshot is one deterministic gzip-compressed JSON document:

```
backups/portable/tradely-backup-s6-v1-YYYYMMDDTHHMMSSZ.json.gz
```

Envelope fields:

- `format` / `format_version` — `tradely-portable-backup`, currently `1`
- `created_at` — ISO-8601 UTC timestamp
- `application_version`, `schema_version`, `scope`
- `record_counts` and `excluded_record_counts`
- `data_fingerprint` — SHA-256 of the canonical JSON data
- `data` — essential tables only, rows ordered by a stable key
- `checksum` — SHA-256 over every metadata field and every row

Financial columns (`quantity`, `price`, `fees`, `amount`, `actual_amount`) are
exported as decimal **strings**, never JSON floats. On restore SQLite converts
them back to its `REAL` storage; the round-trip is exact for every value that was
originally stored as a double.

The format is forward-compatible: newer schema versions are rejected unless
`--allow-newer-schema` is passed, and older versions are accepted because the
restore path inserts only columns that exist in the current schema.

## 3. Directory layout and Git boundary

| Path | Git | Purpose |
| --- | --- | --- |
| `data/tradely.sqlite3`, `-wal`, `-shm` | ignored | Active database; never committed |
| `data/backups/*.sqlite3` | ignored | Legacy pre-migration full copies; local only |
| `data/local_backups/*.json.gz` | ignored | Local retention and pre-restore safety snapshots |
| `backups/portable/*.json.gz` | **tracked** | The only portable backups that enter Git |
| `.env`, `.manus/`, `.work/`, research data | ignored | Secrets and generated artefacts |

`.gitignore` was updated and `.env` plus `.manus/` were removed from the index
with `git rm --cached`; the local copies remain on disk.

## 4. Lifecycle triggers

- **Startup**: prune regenerable analytics snapshots, checkpoint the WAL, and
  create a Git backup only when the essential-data fingerprint changed.
- **Shutdown**: checkpoint the WAL and create local + Git backups if changed.
- **Manual/API**: `python -m app.backup.cli create` or `POST /api/backup/create`.
- **Pre-restore**: always create a local safety snapshot before touching data.
- **Unchanged data**: skipped using `data_fingerprint`, so repeated launches do
  not add files.
- **Concurrency**: a cross-process lock file prevents overlapping operations;
  stale locks and stale `.tmp` files are cleaned up automatically.

## 5. Limits and retention

| Control | Value |
| --- | --- |
| Combined tracked backup hard limit | 100 MiB |
| Warning threshold | 75 MiB |
| Single backup hard limit | 90 MiB |
| Git retention | 2 newest valid snapshots |
| Local retention | 10 newest valid snapshots |
| Local directory limit | 400 MiB |

Every new file is written atomically (temp file + `fsync` + `os.replace`) and
read back/validated before older files are pruned. A prune never removes the
newest valid snapshot, even when the retention count is 1. Invalid Git backups
are moved to `data/local_backups/quarantine/` rather than silently deleted.

Current tracked backup footprint: **2 files, 172,448 bytes (~0.16 MiB)**.

## 6. Restore procedure

```bash
# Validate first
python -m app.backup.cli verify backups/portable/<file>.json.gz

# Dry run inside a transaction that is rolled back
python -m app.backup.cli restore backups/portable/<file>.json.gz --dry-run

# Real restore; creates a local safety snapshot first
python -m app.backup.cli restore backups/portable/<file>.json.gz
```

Restore guarantees:

- format, checksum, fingerprint, record counts and required columns validated
- schema compatibility checked before writing
- one `BEGIN IMMEDIATE` transaction; any failure rolls back completely
- `PRAGMA defer_foreign_keys` plus `PRAGMA foreign_key_check` before commit
- ledger invariants re-validated for every affected instrument
- duplicate detection by idempotency key / natural key; no silent duplicates
- primary keys are preserved when free; on a collision the row is inserted with a
  new id and the remap is reported in the restore summary
- existing rows are never overwritten unless `--overwrite` is explicit
- newer local data is not replaced by an older backup without authorization
- post-restore application reads (`watchlist`, ledger, instruments) verified by tests

## 7. SQLite optimisation

Cause of the 2.84 GB file: `market_analytics_snapshots.payload` stored a full
compressed candle + indicator bundle for **every** OHLCV fingerprint. 1,098
snapshots occupied **2.475 GB** while only the newest complete snapshot per
instrument/interval is read by the UI.

Actions taken:

- retention of the newest 2 snapshots per series (145 series), with strategy
  variants deleted in the same transaction
- retention also runs after every snapshot publication, so growth is bounded
- WAL checkpoint on shutdown and after maintenance
- `VACUUM` only when explicitly requested, with a free-space guard
- market bars are **not** pruned: their primary key already prevents exact
  duplicates, and rows with different `source`/`adjustment_status` are
  intentional variants (756,343 overlapping groups, **0 exact duplicates**)

Result:

| Metric | Before | After |
| --- | ---: | ---: |
| Database + WAL/SHM | 2,907,529,216 B (2.71 GiB) | 998,404,096 B (0.93 GiB) |
| Analytics snapshot payload | 2,475,123,427 B | 446,320,997 B |
| Analytics snapshot rows | 1,098 | 274 |
| `PRAGMA integrity_check` | `ok` | `ok` |
| `PRAGMA user_version` | 6 | 6 |
| Freelist pages | 188 | 1,242 |

Reduction: **1,909,125,120 bytes (~65.7%)**. The `after` figure is measured
immediately after `VACUUM`; with the application running and a small WAL the
total is about 1.00 GB.

## 8. Git safeguards

`scripts/check_backup_limits.py` inspects the Git index and rejects:

- combined `backups/portable/*.json.gz` above 100 MiB (warns at 75 MiB)
- any single backup above 90 MiB
- any tracked file above 100 MiB
- `.env`/`.env.*` (except `.env.example`), SQLite/WAL/SHM, `node_modules`,
  `.work/`, `.manus/`, archives/bundles, research CSV/JSONL, partial writes

Install the hook once per clone:

```bash
git config core.hooksPath .githooks
```

Run it manually with:

```bash
python scripts/check_backup_limits.py
```

## 9. Git history cleanup plan (not executed)

The current history contains blobs far above GitHub's 100 MiB limit. The pack is
~439 MiB, and total blob bytes across history are ~2.26 GB. Largest blobs:

| Blob | Size |
| --- | ---: |
| `data/tradely.sqlite3` | 435.38 MiB (two blobs) |
| `.work/push-cleanup-full.bundle` | 149.89 MiB |
| `research/optimization/100k_2h/checkpoints/2h/*.jsonl` | 131–132.5 MiB |
| `research/data/BTCUSDT/BTCUSDT_5minutes.csv` | 88.18 MiB |
| `research/optimization/.../all_results.csv` | 65–67 MiB |
| `frontend.zip` | up to 40.49 MiB |
| `.work/push-cleanup.bundle` | 33.61 MiB |
| `research/data/BTCUSDT/BTCUSDT_15minutes.csv` | 30.02 MiB |

Recommended, **not performed**:

1. Take a fresh portable backup and a local full SQLite copy.
2. `git filter-repo --strip-blobs-bigger-than 50M --replace-text <(echo 'API_KEY==>REDACTED')`
   (or BFG), then `git gc --prune=now --aggressive`.
3. Verify `git rev-list --objects --all | git cat-file --batch-check` has no
   blob over 100 MiB.
4. Only with explicit owner authorization, force-push and ask every clone to
   re-clone. History rewriting is intentionally left out of this change.

## 10. Verification report

- Portable backup: 86,256 bytes, 6 tables, 1,799 rows, checksum verified.
- Tracked backup footprint: 2 files, 172,448 bytes (0.16 MiB), limit 100 MiB.
- Tracked worktree: 807 files, 9,614,103 bytes (9.17 MiB), no file >100 MiB.
- Backend tests: `backend/tests/test_backup.py` — **17 passed**.
- Full backend suite: all tests pass except two pre-existing, time-dependent
  quote tests that fail only when the suite runs long enough for the module-level
  `NOW` timestamp to age past the "live" window; they pass when run alone.
- `PRAGMA integrity_check`: `ok`.
- Local full SQLite database and all user ledger/watchlist rows retained.
- A real `BUY_TO_COVER` ledger entry was recorded through the running app after
  maintenance; the final portable backup was taken afterwards and contains all
  **4** `holding_transactions` rows, proving new user data is captured.
- `.env` and `.manus/` untracked with local copies retained.
- Remaining oversized files exist only in Git history, not in the current tree.

## 11. Risks and limitations

- The two quote tests are flaky by design (wall-clock dependent), not caused by
  this change; consider freezing their clock in a follow-up.
- `VACUUM` requires exclusive access and free disk space; it is disabled by
  default on startup and available through `maintain --vacuum`.
- Market bars from multiple sources overlap; consolidating them is a data-quality
  decision that needs provider-specific validation and is intentionally not done.
- A backup only covers SQLite-resident data. Browser `localStorage` preferences
  and `.env` configuration are out of scope by design.
- History rewriting and force-pushing remain manual, owner-authorized steps.
