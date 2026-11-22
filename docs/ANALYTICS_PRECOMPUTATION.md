# Analytics precomputation (migration stage)

## Architecture and current behavior

The additive precomputation path is introduced alongside the legacy synchronous analytics endpoint. At application lifespan startup, the engine reconciles watchlist instruments and enqueues initial jobs; a single bounded background thread claims durable work from SQLite. Provider calls and analytics calculations happen in that worker, not in the prepared-data GET routes. Analytics UI selection reads the application-wide in-memory store populated by the app-start manifest hydrator and IndexedDB; missing data is reported instead of falling back to the old endpoint. Manual refresh submits a queue request and retains the current complete in-memory snapshot.

The active migration is intentionally non-destructive. `/api/instruments/{symbol}/analytics-snapshot` remains for non-migrated/legacy consumers during rollout; do not treat that legacy endpoint as read-only.

## Persistence and migration

Database schema version 4 adds:

- `market_bars`: idempotently upserted OHLCV keyed by canonical instrument, interval, timestamp, adjustment state and source.
- `market_analytics_snapshots`: compressed JSON (gzip) payload with SHA-256 checksum and fingerprint/version/provenance metadata.
- `strategy_snapshots`: distinct payloads keyed by market fingerprint, strategy version/configuration, direction and position side.
- `analytics_jobs`: persistent priority queue with attempts, leases, owner, retries and last error.

The existing additive migration machinery creates a consistent pre-migration backup when an existing database's schema version is upgraded. No user tables are dropped or recreated.

History requests use explicit finite calendar-day limits in `services/analytics_precompute.py` and pass `full_history=False`. These are current bounded defaults, not a claim that every venue/provider can return all required history. Intraday limits are intentionally finite; unsupported intervals are excluded.

## Job lifecycle

Jobs are deduplicated by active `(instrument_id, interval, job_type)`, claimed under `BEGIN IMMEDIATE`, and leased for five minutes. A worker restart makes expired work claimable. Errors are retained and retried with exponential backoff up to the job's attempt cap. Each pipeline build validates OHLCV, calculates the existing full indicator/rating/strategy functions, compresses the complete payload, then publishes bars, market snapshot, and strategy variants in a database transaction. A failure is recorded without deleting an older READY snapshot.

The first engine uses one worker thread to bound TradingView and CPU load. Multi-process scheduler election, exchange-calendar-aware periodic refresh, fine-grained partial indicator invalidation, adaptive backpressure, and expanded job history are not yet implemented.

## Snapshot dependencies and invalidation

Market snapshot identity includes canonical instrument, interval, OHLCV fingerprint, source, adjustment state and schema/calculation versions. Strategy outputs are stored separately for the finite currently supported direction modes (`long_only`, `short_only`, `long_short`) and position states (`NONE`, `LONG`, `SHORT`). Fingerprint changes create a different immutable market snapshot identity and new strategy rows; old successful rows are retained.

Portfolio transaction mutation hooks that automatically enqueue only affected strategy variants, provider/configuration invalidation, automated snapshot repair, and retention cleanup are not yet wired.

## API

- `GET /api/analytics/precomputed/index`: compact watchlist/timeframe manifest.
- `GET /api/analytics/precomputed/{instrument_id}/{interval}`: persisted snapshot and strategy variants only; missing results return HTTP 404 with `MISSING` status.
- `GET /api/analytics/precomputed/{instrument_id}/bundle`: prepared intervals for an instrument (currently only already-READY data).
- `POST /api/analytics/precompute/refresh?instrument_id=...&interval=...`: queue-only refresh.
- `GET /api/analytics/precompute/status`: worker/job counts and provider-request counter.

Prepared GET handlers read the database and verify checksums; they never invoke market retrieval, indicator calculation, TV rating or strategy functions.

## Frontend hydration

At application bootstrap, the hydrator requests the watchlist and compact prepared manifest, reconciles the manifest with versioned IndexedDB, and downloads READY snapshots using bounded concurrency. The reactive store provides synchronous per-instrument/timeframe lookups and keyed subscriptions. Local snapshots with a fingerprint mismatch are not promoted. Analytics timeframe/instrument/strategy direction selections use this store; the Analytics page no longer owns complete-snapshot prefetching. Live quote state remains separate from stored completed-candle data.

IndexedDB currently has a versioned store, atomic bundle writes, checksum/fingerprint consistency checks, and oldest-first eviction on quota pressure. Hydration progress is available from the hydrator service; it is not yet exposed through an application-wide status panel.

## Verification

The backend regression suite includes additive migration, active-job deduplication, expired lease recovery, gzip/checksum validation and a prepared-GET zero-provider-call test. The existing backend suite is run with `python -m pytest backend/tests -q`; frontend checks use `npm run build` and `npm test -- --run` from `frontend/`.

No P95 or end-to-end performance target is claimed yet. Remaining acceptance work includes broader worker pipeline integration tests, browser IndexedDB tests, automated watchlist/portfolio invalidation, periodic session-aware refresh, status dashboard, performance benchmarks and full failure/restart scenarios. The README and these notes describe a migration stage, not completed zero-latency acceptance.
