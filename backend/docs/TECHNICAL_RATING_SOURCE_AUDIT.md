# Tradely Technical Rating source audit

**Verification date:** 21 November 2026  
**Purpose:** distinguish TradingView's library release number from the Pine language version and record the independently checked calculation provenance used by Tradely.

## 1. Version conclusion

The phrase “TechnicalRating v3” does **not** mean the implementation is Pine Script v3. TradingView's official TechnicalRating publication says that its v3 release, dated 29 November 2024, upgraded the library to **Pine Script v6** and updated the technical-rating conditions to align with the Screener and symbol summary. The official page still identifies v3 as the published TechnicalRating release in the version information checked for this audit.

TradingView's separate **Technical Ratings on Chart** indicator has a v4 release. Its release notes say that it was upgraded to Pine Script v6 and imports the latest TechnicalRating library. It is a chart-facing indicator wrapper; it is not evidence that the underlying TechnicalRating library itself is version 4 or 6.

TradingView's separate `ta` library has advanced beyond v9: the official publication lists v9 (26 November 2024), v10 (24 April 2025), v11 (7 November 2025), v12 (6 December 2025), v13 (10 July; year not printed in the release note) and v14 (4 August; year not printed in the release note). That does **not** justify changing TechnicalRating's pinned dependency from `TradingView/ta/9` to v14. The TechnicalRating v3 implementation is tied to its published dependency and should be reproduced as such until TradingView publishes a newer TechnicalRating release that changes it.

Official references:

- [TradingView TechnicalRating library](https://www.tradingview.com/script/jDWyb5PG-TechnicalRating/)
- [TradingView Technical Ratings on Chart](https://www.tradingview.com/script/dHhrROXa-Technical-Ratings-on-Chart/)
- [TradingView `ta` library and release history](https://www.tradingview.com/script/BICzyhq0-ta/)
- [TradingView Screener ratings and constituent conditions](https://www.tradingview.com/support/solutions/43000475547-what-do-the-ratings-in-the-screener-mean/)
- [Pine Script v6 variable declaration example showing EMA recursion](https://www.tradingview.com/pine-script-docs/language/variable-declarations/)

## 2. What the current Tradely source was checked against

The uploaded project contains these Python implementation files:

- `app/services/pine_ta.py`
- `app/services/tv_technical_rating.py`
- `app/services/technical_rating_cache.py`

The uploaded project did **not** contain the expected raw Pine reference files `TechnicalRating-v3.pine` or `ta-v9.pine`. Therefore this audit does not claim that those complete raw files were present locally or compiled in a TradingView Pine environment. The public TradingView publication/version pages, current Screener Help Center, Pine v6 documentation, and the local Python source were checked independently. Where direct raw-source verification was unavailable, that limitation is called out rather than inventing a newer library version.

The current Python rating service already exposes the expected 15 moving-average and 11 oscillator constituents, source provenance, indicator components, aggregate ratings and explicit unavailable values. Its overall calculation uses the mean of the MA-group and oscillator-group ratings when both are available, and falls back to the one available group when only one group is available. This is the source-level aggregation behaviour implemented in the current rating engine; do not replace it with an unweighted mean of all available 26 constituent signals unless the authoritative Pine code changes.

## 3. Verified calculation details and discrepancies

### EMA initialization correction

A concrete mismatch was found in `pine_ta.py`: the previous `ema()` implementation reused the SMA-seeded recursive helper intended for Wilder RMA. That delayed EMA output until `length` valid samples and produced a different initial trajectory from Pine's EMA recurrence.

TradingView's Pine v6 documentation shows the EMA recurrence with the prior EMA falling back to the current source on the first bar:

`ema := (1.0 - alpha) * nz(ema[1], close) + alpha * close`

with `alpha = 2.0 / (length + 1.0)`. An independent TA-Lib seeding study also distinguishes TradingView `ta.ema`'s first-source-value seed from the SMA seed used by `ta.rma` and TA-Lib's default EMA. Tradely's Python EMA now seeds from the first valid source value, while RMA keeps the first-full-SMA seed. The test suite has been updated to lock in that distinction.

This corrects the Python primitive's startup semantics. It does not, by itself, prove exact live parity with TradingView because the upstream candle history, adjustment policy and realtime bar state must also match.

### ADX Sell condition

The current TradingView Screener Help Center page says both ADX Buy and ADX Sell require ADX above 20 and rising; +DI versus -DI determines direction. The current Tradely `rating_adx_14` condition uses that same rule. This audit therefore does not retain an older Help Center wording that described falling ADX for Sell.

### Bull/Bear Power period

The TechnicalRating overview text on TradingView's library page lists Bull Bear Power with a period of 50, but the Screener-specific conditions and the published v3 source representation used by Tradely describe the EMA-13 based bull/bear power components. Tradely keeps the 13-period calculation and exposes bull power, bear power, EMA-13 and EMA-50 references. This is a documentation/implementation discrepancy that should be resolved only from a directly inspectable current Pine library source or an identical-data TradingView test, not by guessing from the overview bullet.

### TA dependency version

The separate `ta` library's newer releases add or refine functions such as volume-delta and dynamic-length helpers. Those release notes do not establish that the TechnicalRating v3 import should be bumped. Tradely therefore retains the `TradingView/ta/9` dependency identity associated with the TechnicalRating v3 source, rather than silently switching to v14 and changing the calculation baseline.

## 4. Conditions for exact parity

Even when the calculation rules are correct, TradingView's displayed result can differ from Tradely when any of these inputs differ:

- Exchange and instrument mapping (including spot versus perpetual market).
- OHLCV candles, historical depth or candle timestamp boundaries.
- Volume semantics and adjustment policy.
- Whether the latest candle is still forming or confirmed.
- The historical start point used to initialise recursive indicators.

To claim exact parity, compare both systems against identical timestamped OHLCV rows and the same bar-confirmation state. The backend snapshot endpoint includes an OHLCV fingerprint to make that comparison reproducible. A matching instrument label alone is not enough.

## 5. Provenance labels

Tradely now labels the rating implementation as:

- **Library:** TradingView TechnicalRating v3
- **Pine language:** v6
- **Dependency:** TradingView/ta/9 (pinned by the v3 implementation)

A higher number in the separate `ta` library is not a newer TechnicalRating algorithm release.
