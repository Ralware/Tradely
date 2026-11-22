# Analytics precomputation migration audit

## Current dependency path

- `frontend/src/main.tsx` mounts `SelectedInstrumentProvider`; there is currently no application-start analytics hydrator.
- `AnalysisWorkspace.tsx` uses `useApi` to call `analysisService.getAnalyticsSnapshot`, maintains a page-owned prefetch effect for alternate timeframes, and its refresh/retry actions directly fetch analytics. The current working tree contains user edits in this file and related watchlist, rating, page, test and stylesheet files; those changes must be preserved.
- `AnalysisWatchlist.tsx` has a working-tree change that invokes `prefetchWatchlistSnapshots`; that is also page-owned prefetch and must be migrated, not discarded.
- `analysisService.ts` owns the in-memory market cache, alias/inflight maps, generations, TTLs, and calls `/api/instruments/{id}/analytics-snapshot`.
- `SelectedInstrumentContext.tsx` owns selected instrument/timeframe URL state and quotes; `quoteHub.ts` and `useQuotes.ts` provide shared quote support. `PriceChart.tsx` is the chart lifecycle boundary.
- Backend `routes.py` implements `/analytics-snapshot` as a synchronous path: `market_service.candles` -> `ohlcv_fingerprint` -> `compute_indicators` -> `position_side_at` -> `evaluate_trend_breakout` -> `_cached_tv_rating_snapshot`/`build_tv_technical_summary` -> serialization and `save_signal`.
- `MarketService.candles` defaults `full_history=True`; analytics route currently passes `days` but not `full_history=False`.
- SQLite setup is additive/backup-aware in `core/database.py`, currently schema version 3, WAL is enabled. `main.py` has a minimal FastAPI lifespan and initializes database/provider services at module import; it has no analytics worker lifecycle.
- Canonical timeframe lists are defined in `instruments/catalogue_data.py` and surfaced by `capabilities_for`. The indicator engine is `services/indicators.py`; the TV rating implementation is `services/tv_technical_rating.py`; strategy is `services/strategy.py` and supports direction and position inputs.

## Safe migration constraints

1. Keep existing analytics endpoint and other market endpoints available while adding persisted storage and read-only prepared-data routes alongside them.
2. Add analytics schema only through an additive versioned migration; use the existing consistent pre-migration backup convention. Never change live SQLite files directly during code work.
3. Use canonical instrument IDs, capability-derived timeframe sets, bounded configured history, and the existing TradingView adapter and calculation functions.
4. Keep market snapshots independent of direction/position strategy variants; publish only validated complete payloads and retain the previous good snapshot on errors.
5. Migrate frontend to application-start manifest/bundle hydration only after the new API contracts and store are tested. The target page interaction must be local store selection, not fallback to the legacy endpoint.

## Implementation/testing status

This audit is the starting dependency map. Delivery status and concrete limitations must be updated after each implementation phase; no performance or zero-request acceptance claim is made until measured by tests.
