import type {
  CandlestickData,
  HistogramData,
  UTCTimestamp,
} from 'lightweight-charts';
import type { ReconciledCandle } from './candleReconcile';

export interface CandlePointColors {
  up: string;
  down: string;
  neutral: string;
  volumeUp: string;
  volumeDown: string;
  volumeNeutral: string;
}

export interface CandleSeriesLike {
  setData(data: CandlestickData<UTCTimestamp>[]): void;
  update(bar: CandlestickData<UTCTimestamp>): void;
}

export interface VolumeSeriesLike {
  setData(data: HistogramData<UTCTimestamp>[]): void;
  update(bar: HistogramData<UTCTimestamp>): void;
}

export interface ChartSyncState {
  key: string;
  candles: ReconciledCandle[];
}

export function candlePoint(
  candle: ReconciledCandle,
  colors: CandlePointColors,
): CandlestickData<UTCTimestamp> {
  const color = candle.close > candle.open
    ? colors.up
    : candle.close < candle.open
      ? colors.down
      : colors.neutral;
  return {
    time: candle.time as UTCTimestamp,
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
    color,
    borderColor: color,
    wickColor: color,
  };
}

export function volumePoint(
  candle: ReconciledCandle,
  colors: CandlePointColors,
): HistogramData<UTCTimestamp> | null {
  // Unknown volume is omitted rather than drawn as a fabricated zero.
  if (candle.volume === null) return null;
  return {
    time: candle.time as UTCTimestamp,
    value: candle.volume,
    color: candle.close > candle.open
      ? colors.volumeUp
      : candle.close < candle.open
        ? colors.volumeDown
        : colors.volumeNeutral,
  };
}

function sameCandle(left: ReconciledCandle, right: ReconciledCandle): boolean {
  return left.time === right.time
    && left.open === right.open
    && left.high === right.high
    && left.low === right.low
    && left.close === right.close
    && left.volume === right.volume
    && left.status === right.status;
}

function canUpdateNewest(
  previous: ChartSyncState | null,
  key: string,
  candles: ReconciledCandle[],
): boolean {
  if (!previous || previous.key !== key || previous.candles.length === 0) return false;
  const sameLength = candles.length === previous.candles.length;
  if (!sameLength && candles.length !== previous.candles.length + 1) {
    return false;
  }
  const prefixLength = previous.candles.length - 1;
  for (let index = 0; index < prefixLength; index += 1) {
    if (!sameCandle(previous.candles[index], candles[index])) return false;
  }
  // When appending, the previous newest bar must still occupy its old slot.
  if (!sameLength && !sameCandle(previous.candles[prefixLength], candles[prefixLength])) {
    return false;
  }
  // `update()` requires a monotonically newer bar; a time regression must be
  // written with `setData` instead.
  if (candles[candles.length - 1].time < previous.candles[previous.candles.length - 1].time) {
    return false;
  }
  // A null volume cannot be removed with update(); force a full setData.
  return candles[candles.length - 1]?.volume !== null;
}

/**
 * Push reconciled candles into the chart series. History or key changes use
 * `setData`; a changed newest bar uses `update` so the viewport is stable.
 */
export function syncChartSeries(params: {
  key: string;
  candles: ReconciledCandle[];
  previous: ChartSyncState | null;
  candleSeries: CandleSeriesLike;
  volumeSeries: VolumeSeriesLike;
  colors: CandlePointColors;
}): ChartSyncState {
  const { key, candles, previous, candleSeries, volumeSeries, colors } = params;
  // Identical payloads (the common poll case) must not touch the chart.
  if (
    previous
    && previous.key === key
    && previous.candles.length === candles.length
    && previous.candles.every((candle, index) => sameCandle(candle, candles[index]))
  ) {
    return previous;
  }
  const candleData = candles.map((candle) => candlePoint(candle, colors));
  const volumeData = candles.flatMap((candle) => {
    const point = volumePoint(candle, colors);
    return point ? [point] : [];
  });

  if (canUpdateNewest(previous, key, candles)) {
    candleSeries.update(candleData[candleData.length - 1]);
    const lastVolume = volumeData[volumeData.length - 1];
    if (lastVolume) {
      volumeSeries.update(lastVolume);
    } else {
      volumeSeries.setData(volumeData);
    }
  } else {
    candleSeries.setData(candleData);
    volumeSeries.setData(volumeData);
  }

  return { key, candles };
}

export interface LogicalRange {
  from: number;
  to: number;
}

/**
 * Restoring a stored viewport must not hide the newest completed/forming bars.
 * Shift (never stretch) the stored range so the last `minBars` are visible.
 */
export function ensureRangeIncludesLatest(
  range: LogicalRange,
  lastIndex: number,
  minBars = 2,
): LogicalRange {
  if (lastIndex < 0) return range;
  const minimumFrom = lastIndex - Math.max(0, minBars - 1);
  const maximumTo = lastIndex + 1;
  const span = Math.max(1, range.to - range.from);

  if (range.to < maximumTo) {
    const shift = maximumTo - range.to;
    return { from: range.from + shift, to: range.to + shift };
  }
  if (range.from > minimumFrom) {
    const shift = minimumFrom - range.from;
    return { from: range.from + shift, to: range.to + shift };
  }
  if (span < minBars) {
    return { from: lastIndex - minBars + 1, to: lastIndex + 1 };
  }
  return range;
}
