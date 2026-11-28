import { describe, expect, it, vi } from 'vitest';
import type { CandleStatus, ReconciledCandle } from './candleReconcile';
import {
  ensureRangeIncludesLatest,
  syncChartSeries,
  type CandlePointColors,
  type CandleSeriesLike,
  type ChartSyncState,
  type VolumeSeriesLike,
} from './chartSeriesSync';

const BASE = Math.floor(Date.UTC(2026, 10, 27, 18, 0, 0) / 1000);
const colors: CandlePointColors = {
  up: '#00ff00',
  down: '#ff0000',
  neutral: '#888888',
  volumeUp: 'rgba(0,255,0,0.2)',
  volumeDown: 'rgba(255,0,0,0.2)',
  volumeNeutral: 'rgba(128,128,128,0.2)',
};

function reconciled(
  time: number,
  close: number,
  status: CandleStatus = 'final',
  volume: number | null = 10,
): ReconciledCandle {
  return {
    timestamp: new Date(time * 1000).toISOString(),
    time,
    open: close - 1,
    high: close + 2,
    low: close - 2,
    close,
    volume,
    status,
  };
}

function series() {
  return {
    setData: vi.fn(),
    update: vi.fn(),
  };
}

describe('chart series synchronization', () => {
  it('sends unique, ordered candles and preserves OHLC', () => {
    const candleSeries = series() as unknown as CandleSeriesLike;
    const volumeSeries = series() as unknown as VolumeSeriesLike;
    const candles = [reconciled(BASE, 101), reconciled(BASE + 60, 102, 'forming')];

    syncChartSeries({
      key: 'k', candles, previous: null, candleSeries, volumeSeries, colors,
    });

    const points = (candleSeries.setData as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(points.map((point: { time: number }) => point.time)).toEqual([BASE, BASE + 60]);
    expect(points[0]).toMatchObject({ open: 100, high: 103, low: 99, close: 101 });
    expect(points[1]).toMatchObject({ open: 101, high: 104, low: 100, close: 102 });
  });

  it('omits unknown volume instead of fabricating zero', () => {
    const candleSeries = series() as unknown as CandleSeriesLike;
    const volumeSeries = series() as unknown as VolumeSeriesLike;

    syncChartSeries({
      key: 'k',
      candles: [reconciled(BASE, 101, 'final', null), reconciled(BASE + 60, 102)],
      previous: null,
      candleSeries,
      volumeSeries,
      colors,
    });

    const volume = (volumeSeries.setData as ReturnType<typeof vi.fn>).mock.calls[0][0];
    expect(volume).toHaveLength(1);
    expect(volume[0]).toMatchObject({ time: BASE + 60, value: 10 });
  });

  it('updates only the newest bar when the forming OHLC changes', () => {
    const candleSeries = series() as unknown as CandleSeriesLike;
    const volumeSeries = series() as unknown as VolumeSeriesLike;
    const first = [reconciled(BASE, 101), reconciled(BASE + 60, 102, 'forming')];

    const state = syncChartSeries({
      key: 'k', candles: first, previous: null, candleSeries, volumeSeries, colors,
    });
    const second = [first[0], reconciled(BASE + 60, 105, 'forming')];
    syncChartSeries({
      key: 'k', candles: second, previous: state, candleSeries, volumeSeries, colors,
    });

    expect(candleSeries.setData).toHaveBeenCalledTimes(1);
    expect(candleSeries.update).toHaveBeenCalledTimes(1);
    expect((candleSeries.update as ReturnType<typeof vi.fn>).mock.calls[0][0])
      .toMatchObject({ time: BASE + 60, close: 105 });
  });

  it('appends a new bar with update and uses setData for a key change', () => {
    const candleSeries = series() as unknown as CandleSeriesLike;
    const volumeSeries = series() as unknown as VolumeSeriesLike;
    const first = [reconciled(BASE, 101)];
    const state: ChartSyncState = syncChartSeries({
      key: 'k', candles: first, previous: null, candleSeries, volumeSeries, colors,
    });

    const appended = [first[0], reconciled(BASE + 60, 102, 'forming')];
    syncChartSeries({
      key: 'k', candles: appended, previous: state, candleSeries, volumeSeries, colors,
    });
    expect(candleSeries.update).toHaveBeenCalledTimes(1);

    syncChartSeries({
      key: 'other', candles: appended, previous: state, candleSeries, volumeSeries, colors,
    });
    expect(candleSeries.setData).toHaveBeenCalledTimes(2);
  });

  it('keeps the last two bars visible after a stored range restore', () => {
    expect(ensureRangeIncludesLatest({ from: 0, to: 2 }, 5)).toEqual({ from: 4, to: 6 });
    expect(ensureRangeIncludesLatest({ from: 10, to: 20 }, 5)).toEqual({ from: 4, to: 14 });
    expect(ensureRangeIncludesLatest({ from: 2, to: 8 }, 5)).toEqual({ from: 2, to: 8 });
  });
});
