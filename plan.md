# Tradely application-wide UI/UX redesign

## Objective
Refactor the existing React frontend into one cohesive, professional trading terminal while preserving routes, API integrations, calculations, state management, chart interactions, and existing data-driven functionality.

## Design direction
**Design movement:** institutional trading terminal / Bloomberg-inspired information density.

**Core principles:** pitch-black flat surfaces; compact controls; one-pixel separators; strong tabular alignment.

**Color philosophy:** `#000000` is the canvas, `#080808` and `#0D0D0D` are opaque hierarchy surfaces, `#1C1C1C` separates regions, and blue/red/green encode active, negative, and positive information rather than decoration.

**Layout paradigm:** a shared horizontal shell with page content below it; Analytics uses a wide workspace plus a separately scrollable right watchlist partition.

**Signature elements:** thin blue active nav underline; compact mono-number treatment for market values; flat bordered sections with restrained 2px radii.

**Interaction philosophy:** immediate, keyboard-friendly controls with subtle opaque hover states; no glass, blur, gradients, glow, or decorative motion.

**Typography:** existing system/Inter stack, compact 12–14px body text, semibold section labels, tabular numerals for financial values.

**Brand essence:** a focused local-first quantitative market terminal for clarity, discipline, and fast comparison.

## Implementation approach
- Consolidate the shared shell around the existing `TopNav`, keeping exactly Watchlist, Analytics, Portfolio, Backtesting, and News.
- Preserve `InstrumentSearch` behavior and URL-driven instrument selection while styling it as an integrated top-bar control.
- Standardize global tokens, buttons, cards, tabs, tables, loading states, notice states, scrollbars, and chart containers in `frontend/src/styles/index.css` and Tailwind tokens.
- Keep Analytics functionality intact and refine its existing main workspace/right watchlist split, responsive drawer, gauges, chart, indicators, risk, candles, and news preview.
- Apply the same shared visual language to Watchlist, Portfolio, Backtesting, and News page composition without adding functionality or fabricated content.
- Remove or retire legacy vertical-sidebar presentation and avoid duplicate page-specific navigation.
- Add/maintain the route manifest for the existing five application routes if the local Webdev setup requires it.

## Project structure
- `frontend/src/components/layout`: global shell and navigation.
- `frontend/src/components/common`: reusable buttons, cards, states, tabs, fields, icons, and headers.
- `frontend/src/components/analysis`: Analytics workspace, ratings, watchlist, and news preview.
- `frontend/src/components/charts`: chart and indicator renderers.
- `frontend/src/components/tables`: data tables for market, portfolio, and analysis views.
- `frontend/src/pages`: route-level composition for the five application sections.
- `frontend/src/services`, `hooks`, `contexts`, `utils`: unchanged data, state, and domain behavior.
