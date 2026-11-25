# Tradely redesign outcomes

## Shared terminal shell and navigation
- [ ] The application uses one shared shell with a full-width horizontal top navigation bar.
- [ ] The navigation contains exactly Watchlist, Analytics, Portfolio, Backtesting, and News, with Tradely on the left and the existing global instrument search integrated on the right.
- [ ] Active navigation labels are blue with a thin blue indicator; inactive labels remain white; the vertical sidebar presentation is removed.
- [ ] Existing search recognition, result selection, URL navigation, and keyboard behavior remain functional.

## Global visual system
- [ ] Every page uses the shared pitch-black visual system: `#000000` primary background, `#080808` secondary opaque surface, `#0D0D0D` tertiary opaque surface, `#1C1C1C` borders, `#F5F5F5` primary text, `#929292` secondary text, `#626262` muted text, `#1685FF` accent, `#00C78A` positive, and `#F04452` negative.
- [ ] Shared buttons, inputs, selects, tabs, tables, cards, notices, empty states, error states, loading states, scrollbars, and chart containers use the same flat border, spacing, radius, and typography system.
- [ ] Glassmorphism, blur, gradients, glow, excessive shadows, floating translucent cards, decorative patterns, and unnecessary animation are absent.

## Analytics workspace
- [ ] Analytics preserves instrument information, current price/change, timeframe selection, Technical Ratings, price chart, indicator controls, existing analytical sections, and data accuracy.
- [ ] Technical gauges remain horizontally aligned where space permits, with Oscillators, Overall Technical Rating, and Moving Averages clearly separated.
- [ ] Buy/Sell/Neutral counts remain beneath their respective gauges and remain semantically colored.
- [ ] The price chart remains the existing implementation with pitch-black background, blue increasing candles, white decreasing candles, subtle grid, volume, overlays, OHLC hover information, and existing timeframe behavior.
- [ ] Analytics has a dedicated right-hand Watchlist partition with independent scrolling, compact rows, selected-instrument highlight, sparkline support where present, and add/remove behavior.
- [ ] Responsive Analytics uses the existing watchlist drawer without horizontal overflow or broken controls.

## Watchlist page
- [ ] The dedicated Watchlist page uses the shared terminal language with compact aligned rows, existing prices, percentage changes, charts, sorting/filtering, and add/remove behavior.
- [ ] No fabricated metrics or unrelated columns are introduced.

## Portfolio, Backtesting, and News
- [ ] Portfolio retains overview, account value, holdings, market prices, P&L, transaction history, and buy/sell behavior in compact aligned sections.
- [ ] Backtesting retains all configuration inputs, strategy calculations, result tables, charts, filters, and performance metrics.
- [ ] News retains the existing article list, source/publication data, date filters, empty states, and retrieval behavior.

## Quality
- [ ] All five navigation routes work and share the same topbar.
- [ ] Existing API communication, routing, state, caching, calculations, and chart interactions remain intact.
- [ ] TypeScript checks, tests, and production build pass.
