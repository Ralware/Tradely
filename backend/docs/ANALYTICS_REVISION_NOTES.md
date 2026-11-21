# Tradely Analytics Revision Notes

**Revision date:** 21 November 2026

## UI changes

- Removed the Analytics `Calculation & Data Information` card from the page layout.
- Removed the `Latest Bar` card/panel.
- Moved the existing strategy `SignalCard` (for example, Trend + Donchian 20 Breakout) into the right-hand column beside Signal Distribution.
- Removed the separate Signal tab; the lower tab strip now contains Risk, Indicators and Candles.
- Removed the unused `TechnicalProvenance` component file.
- Kept the existing chart, symbol selection, timeframe selector, watchlist and routing intact.

## Timeframe switching behaviour

- Timeframe changes continue to update the `interval` query parameter with React Router's `setSearchParams`; they do not perform a browser navigation/reload.
- `AnalysisWorkspace` remains mounted while the selected timeframe changes.
- A valid exact snapshot-cache hit is exposed synchronously to the view.
- On a cache miss for the same instrument, `useApi` retains the last complete snapshot and labels it as the previously selected timeframe while the new snapshot is fetched. Gauges, indicator tables, strategy and chart therefore remain from one coherent snapshot instead of being partially replaced.
- Data is never retained across the instrument identity boundary. A symbol change cannot show the previous symbol's snapshot as the new instrument.
- The Lightweight Charts chart instance remains mounted; timeframe changes update the existing series rather than destroying and recreating the chart.
- The existing background timeframe preparation queue remains bounded to two concurrent jobs.

## Calculation/source verification

Independent checks of TradingView's published pages show that the published `TechnicalRating` library is release v3, updated 29 November 2024, and that v3 is Pine Script v6. The separately published `Technical Ratings on Chart` wrapper has a v4 release, is Pine v6, and imports the latest TechnicalRating library. These are distinct version numbers; v3 is not a Pine v3 implementation.

The TradingView TA library page separately lists v14. Its v10-v14 release notes describe other library additions/changes, especially volume-delta/up-down-volume and dynamic-length helpers; a higher `ta` version by itself is not evidence that the TechnicalRating library changed its pinned dependency. The Python implementation retains the TechnicalRating v3 dependency identity (`TradingView/ta/9`) rather than silently changing the dependency.

A local calculation primitive issue was corrected: `pine_ta.ema()` had been sharing the SMA-seeded helper intended for RMA. Pine's EMA recurrence falls back to the current source on the first bar, while RMA uses an SMA seed. EMA and RMA now have separate initialization logic and regression tests.

The current TradingView Screener Help Center describes both ADX Buy and ADX Sell as requiring ADX above 20 and rising, with +DI/-DI determining direction. The Python rating logic already follows this condition, so its ADX rule was preserved.

The supplied ZIPs did not include the raw Pine files `TechnicalRating-v3.pine` or `ta-v9.pine`. This package therefore does not claim that those exact full Pine source files were locally compiled or compared line-by-line. See `TECHNICAL_RATING_SOURCE_AUDIT.md` for detailed provenance, discrepancies and parity limitations.

## Files changed

### Backend

- `app/services/pine_ta.py` — corrected Pine-compatible EMA initialization; retained SMA-seeded RMA.
- `app/services/tv_technical_rating.py` — made the source-version and dependency provenance explicit.
- `tests/test_pine_ta.py` — added EMA first-valid-value and missing-value regression coverage; retained RMA seed coverage.
- `docs/TECHNICAL_RATING_SOURCE_AUDIT.md` — independent TradingView version/source audit and known discrepancies.
- `docs/ANALYTICS_REVISION_NOTES.md` — this implementation note.

### Frontend

- `src/components/analysis/AnalysisWorkspace.tsx` — removed the provenance and latest-bar panels; moved Strategy Signal beside Signal Distribution; kept the remaining tabs; added same-instrument timeframe transition messaging.
- `src/components/charts/PriceChart.tsx` — retains one chart instance and updates its series across timeframe changes.
- `src/hooks/useApi.ts` — exact cached snapshots are read synchronously; same-instrument stale-while-revalidate keeps the prior coherent snapshot visible; stale results are cancelled/ignored; prior-symbol data is not carried across scope changes.
- `src/services/analysisService.ts` — snapshot cache and bounded all-timeframe preparation.
- `src/services/analysisService.test.ts` — cache-hit behaviour regression test.
- `src/components/analysis/TechnicalProvenance.tsx` — removed because the card is no longer part of Analytics and had no remaining imports.

## Verification performed

- `python -m compileall -q app` — passed.
- `python -m pytest -q tests/test_pine_ta.py tests/test_tv_technical_rating.py tests/test_technical_rating_cache.py` — **32 passed**.
- `python -m pytest -q` — **195 passed, 2 failed**. Both failures are existing SPA-serving tests (`/` and client-side routes) because this backend source archive does not include a built `frontend/dist` bundle; backend returns 503 when that build artifact is absent.
- TypeScript syntax transpilation using the globally installed TypeScript compiler API — passed for the five changed TypeScript/TSX source/test files.
- Full TypeScript project type-check, Vitest suite and Vite production build were **not verified**. The ZIP does not include `node_modules`; `npm ci` could not complete in this environment, and the partial dependency tree was removed before packaging.
- No browser-driven visual test or screenshot was produced in this environment.

## Local verification commands

From the frontend directory:

```bash
npm ci
npm run typecheck
npm test
npm run build
```

For the backend SPA-serving tests to pass, build the frontend and place its `dist` output in the location configured by the backend static-file serving code (currently `backend/frontend/dist` in the packaged project layout). For development, run the frontend Vite dev server and backend API separately using the existing project instructions/environment settings.

## Parity limitation

Matching the published source-level calculation rules does not guarantee that TradingView's displayed ratings match if the candle feed, exchange/market mapping, historical depth, volume semantics, adjusted/unadjusted data or realtime candle confirmation state differs. Compare identical timestamped OHLCV inputs before attributing a remaining discrepancy to indicator mathematics.
