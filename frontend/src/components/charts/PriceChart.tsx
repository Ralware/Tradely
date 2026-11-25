import { useEffect, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, IndicatorSeriesRow } from '../../types/api';
import { formatNumber } from '../../utils/format';
import { EmptyState } from '../common/States';

export interface OverlayToggles {
  sma: boolean;
  ema: boolean;
  bollinger: boolean;
}

interface PriceChartProps {
  candles: Candle[];
  series: IndicatorSeriesRow[] | null;
  overlays: OverlayToggles;
  showRsi: boolean;
  showMacd: boolean;
  intraday?: boolean;
  timeframe?: string;
  symbol?: string;
  pricePrecision?: number | null;
  priceMinMove?: number | null;
  height?: number;
}

const overlayGroups: Array<{
  key: keyof OverlayToggles;
  lines: Array<{ field: string; title: string; color: string; dashed?: boolean }>;
}> = [
  {
    key: 'sma',
    lines: [
      { field: 'sma_20', title: 'SMA 20', color: '#d6a45a' },
      { field: 'sma_50', title: 'SMA 50', color: '#2f6feb' },
      { field: 'sma_100', title: 'SMA 100', color: '#8b909a' },
      { field: 'sma_200', title: 'SMA 200', color: '#8f7ee7' },
    ],
  },
  {
    key: 'ema',
    lines: [
      { field: 'ema_20', title: 'EMA 20', color: '#26a69a' },
      { field: 'ema_50', title: 'EMA 50', color: '#38bdf8' },
      { field: 'ema_100', title: 'EMA 100', color: '#fbbf24' },
      { field: 'ema_200', title: 'EMA 200', color: '#f472b6' },
    ],
  },
  {
    key: 'bollinger',
    lines: [
      { field: 'bb_upper', title: 'BB Upper', color: '#6b7280', dashed: true },
      { field: 'bb_mid', title: 'BB Mid', color: '#9ca3af', dashed: true },
      { field: 'bb_lower', title: 'BB Lower', color: '#6b7280', dashed: true },
    ],
  },
];

function toSeconds(timestamp: string): UTCTimestamp | null {
  const millis = Date.parse(timestamp);
  if (Number.isNaN(millis)) {
    return null;
  }
  return Math.floor(millis / 1000) as UTCTimestamp;
}

function numeric(value: number | string | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function candlePoints(candles: Candle[]) {
  return candles.flatMap((candle) => {
    const time = toSeconds(candle.timestamp);
    if (time === null) {
      return [];
    }
    return [
      {
        time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      },
    ];
  });
}

function volumePoints(candles: Candle[]) {
  return candles.flatMap((candle) => {
    const time = toSeconds(candle.timestamp);
    if (time === null) {
      return [];
    }
    return [
      {
        time,
        value: candle.volume,
        color:
          candle.close >= candle.open
            ? 'rgba(47, 111, 235, 0.28)'
            : 'rgba(255, 255, 255, 0.28)',
      },
    ];
  });
}

function seriesPoints(
  series: IndicatorSeriesRow[],
  field: string,
): Array<{ time: UTCTimestamp; value: number }> {
  return series.flatMap((row) => {
    const time = toSeconds(row.timestamp);
    const value = numeric(row[field]);
    return time === null || value === null ? [] : [{ time, value }];
  });
}

function fallbackPrecision(value: number | null | undefined): number {
  if (value === null || value === undefined || !Number.isFinite(value)) return 2;
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return 2;
  if (magnitude >= 1) return 4;
  if (magnitude >= 0.01) return 6;
  if (magnitude >= 0.0001) return 8;
  return 10;
}

function candleStamp(timestamp: string): string {
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return timestamp;
  return `${new Date(parsed).toISOString().slice(0, 16).replace('T', ' ')} UTC`;
}

export function PriceChart({
  candles,
  series,
  overlays,
  showRsi,
  showMacd,
  intraday = false,
  timeframe = '1d',
  symbol = '',
  pricePrecision = null,
  priceMinMove = null,
  height = 380,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const indicatorSeriesRef = useRef<Array<ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>>([]);
  const activeTimeframeRef = useRef<string | null>(null);
  const activeSymbolRef = useRef<string | null>(null);
  const timeRangeAnimationRef = useRef<number | null>(null);
  // Hover time is kept in React state so the HTML legend re-renders on
  // crosshair movement; the values themselves always come from `candles`.
  const [hoveredTime, setHoveredTime] = useState<UTCTimestamp | null>(null);

  const digits =
    typeof pricePrecision === 'number' && Number.isFinite(pricePrecision)
      ? Math.max(0, Math.min(12, Math.trunc(pricePrecision)))
      : fallbackPrecision(candles.length ? candles[candles.length - 1].close : null);
  const minMove =
    typeof priceMinMove === 'number' && Number.isFinite(priceMinMove) && priceMinMove > 0
      ? priceMinMove
      : 10 ** -digits;
  const latestCandle = candles.length ? candles[candles.length - 1] : null;
  const hoveredCandle =
    hoveredTime === null
      ? null
      : candles.find((candle) => toSeconds(candle.timestamp) === hoveredTime) ?? null;
  const displayCandle = hoveredCandle ?? latestCandle;

  // The chart is created once and kept alive across data changes. Timeframe
  // switches only replace series data, so the canvas never unmounts or flashes.
  useEffect(() => {
    const element = containerRef.current;
    if (!element) {
      return;
    }

    const chart: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#0d0f13' },
        textColor: '#8b919b',
        fontSize: 11,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#1a1d22' },
        horzLines: { color: '#1a1d22' },
      },
      rightPriceScale: { borderColor: '#24272e', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: '#24272e',
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#0d0f13' },
        horzLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#0d0f13' },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#24a889',
      downColor: '#e45b63',
      borderVisible: false,
      wickUpColor: '#24a889',
      wickDownColor: '#e45b63',
      priceLineVisible: false,
    });

    const volumeSeries = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: 'volume' },
        priceScaleId: '',
        lastValueVisible: false,
        priceLineVisible: false,
      },
      0,
    );
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;

    const handleCrosshair = (param: MouseEventParams) => {
      // `param.time` is absent when the pointer leaves the plot area, which is
      // exactly when the legend must fall back to the newest candle.
      setHoveredTime(typeof param.time === 'number' ? (param.time as UTCTimestamp) : null);
    };
    chart.subscribeCrosshairMove(handleCrosshair);

    return () => {
      if (timeRangeAnimationRef.current !== null) {
        cancelAnimationFrame(timeRangeAnimationRef.current);
        timeRangeAnimationRef.current = null;
      }
      chart.unsubscribeCrosshairMove(handleCrosshair);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      overlaySeriesRef.current = [];
      indicatorSeriesRef.current = [];
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    // Instrument-specific precision from the provider price scale; candle
    // values themselves are never rounded.
    candleSeriesRef.current?.applyOptions({
      priceFormat: { type: 'price', precision: digits, minMove },
    });
  }, [digits, minMove]);

  useEffect(() => {
    setHoveredTime(null);
  }, [symbol, timeframe]);

  useEffect(() => {
    chartRef.current?.timeScale().applyOptions({
      timeVisible: intraday,
      secondsVisible: false,
    });
  }, [intraday]);

  useEffect(() => {
    const chart = chartRef.current;
    const candleSeries = candleSeriesRef.current;
    const volumeSeries = volumeSeriesRef.current;
    if (!chart || !candleSeries || !volumeSeries || candles.length === 0) {
      return;
    }

    if (timeRangeAnimationRef.current !== null) {
      cancelAnimationFrame(timeRangeAnimationRef.current);
      timeRangeAnimationRef.current = null;
    }
    const timeframeChanged =
      activeTimeframeRef.current !== null && activeTimeframeRef.current !== timeframe;
    const symbolChanged =
      activeSymbolRef.current !== null && activeSymbolRef.current !== symbol;
    const firstLoad = activeTimeframeRef.current === null;
    activeTimeframeRef.current = timeframe;
    activeSymbolRef.current = symbol;
    const timeScale = chart.timeScale();
    const previousRange = timeScale.getVisibleLogicalRange();

    candleSeries.setData(candlePoints(candles));
    volumeSeries.setData(volumePoints(candles));

    // A routine refresh appends bars at the same logical indices, so keep the
    // user's zoom and scroll position instead of snapping back to fitContent.
    if (!firstLoad && !timeframeChanged && !symbolChanged) {
      if (previousRange) {
        timeScale.setVisibleLogicalRange(previousRange);
      }
      return;
    }

    timeScale.fitContent();

    const targetRange = timeScale.getVisibleLogicalRange();
    if (!timeframeChanged || !previousRange || !targetRange) {
      return;
    }

    const targetSpan = targetRange.to - targetRange.from;
    const visibleSpan = Math.min(previousRange.to - previousRange.from, targetSpan);
    const startRange = {
      from: targetRange.to - visibleSpan,
      to: targetRange.to,
    };
    timeScale.setVisibleLogicalRange(startRange);

    const duration = 360;
    let animationStart: number | null = null;
    const animateRange = (now: number) => {
      animationStart ??= now;
      const progress = Math.min(1, (now - animationStart) / duration);
      const eased = progress < 0.5
        ? 4 * progress * progress * progress
        : 1 - Math.pow(-2 * progress + 2, 3) / 2;
      timeScale.setVisibleLogicalRange({
        from: startRange.from + (targetRange.from - startRange.from) * eased,
        to: startRange.to + (targetRange.to - startRange.to) * eased,
      });

      if (progress < 1) {
        timeRangeAnimationRef.current = requestAnimationFrame(animateRange);
      } else {
        timeRangeAnimationRef.current = null;
      }
    };
    timeRangeAnimationRef.current = requestAnimationFrame(animateRange);
  }, [candles, timeframe, symbol]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    for (const overlaySeries of overlaySeriesRef.current) {
      chart.removeSeries(overlaySeries);
    }
    overlaySeriesRef.current = [];
    if (!series || series.length === 0) {
      return;
    }
    for (const group of overlayGroups) {
      if (!overlays[group.key]) {
        continue;
      }
      for (const line of group.lines) {
        const overlaySeries = chart.addSeries(
          LineSeries,
          {
            color: line.color,
            lineWidth: 1,
            lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: false,
            title: line.title,
          },
          0,
        );
        overlaySeries.setData(seriesPoints(series, line.field));
        overlaySeriesRef.current.push(overlaySeries);
      }
    }
  }, [overlays, series]);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) {
      return;
    }
    for (const indicatorSeries of indicatorSeriesRef.current) {
      chart.removeSeries(indicatorSeries);
    }
    indicatorSeriesRef.current = [];
    while (chart.panes().length > 1) {
      chart.removePane(chart.panes().length - 1);
    }
    if (!series || series.length === 0) {
      return;
    }

    let paneIndex = 1;

    if (showRsi) {
      const rsiSeries = chart.addSeries(
        LineSeries,
        {
          color: '#8f7ee7',
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: true,
          priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
        },
        paneIndex,
      );
      rsiSeries.setData(seriesPoints(series, 'rsi_14'));
      for (const level of [70, 30]) {
        rsiSeries.createPriceLine({
          price: level,
          color: '#3a3f4a',
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: false,
          title: '',
        });
      }
      rsiSeries.priceScale().applyOptions({ scaleMargins: { top: 0.15, bottom: 0.15 } });
      chart.panes()[paneIndex]?.setHeight(110);
      indicatorSeriesRef.current.push(rsiSeries);
      paneIndex += 1;
    }

    if (showMacd) {
      const histogram = chart.addSeries(
        HistogramSeries,
        {
          priceLineVisible: false,
          lastValueVisible: false,
          priceFormat: { type: 'price', precision: 3, minMove: 0.001 },
        },
        paneIndex,
      );
      histogram.setData(
        series.flatMap((row) => {
          const time = toSeconds(row.timestamp);
          const value = numeric(row.macd_hist);
          if (time === null || value === null) {
            return [];
          }
          return [
            { time, value, color: value >= 0 ? 'rgba(36, 168, 137, 0.5)' : 'rgba(228, 91, 99, 0.5)' },
          ];
        }),
      );

      const macdLine = chart.addSeries(
        LineSeries,
        { color: '#2f6feb', lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      macdLine.setData(seriesPoints(series, 'macd'));

      const signalLine = chart.addSeries(
        LineSeries,
        { color: '#d6a45a', lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      signalLine.setData(seriesPoints(series, 'macd_signal'));

      chart.panes()[paneIndex]?.setHeight(120);
      indicatorSeriesRef.current.push(histogram, macdLine, signalLine);
    }
  }, [series, showRsi, showMacd]);

  useEffect(() => {
    chartRef.current?.applyOptions({
      timeScale: { timeVisible: intraday, secondsVisible: false },
    });
  }, [intraday]);

  const tone =
    displayCandle === null
      ? 'text-terminal-muted'
      : displayCandle.close > displayCandle.open
        ? 'text-terminal-green'
        : displayCandle.close < displayCandle.open
          ? 'text-terminal-red'
          : 'text-terminal-muted';

  return (
    <div className="relative" style={{ height }}>
      <div ref={containerRef} className="h-full w-full" aria-label="Price chart" />
      {displayCandle ? (
        <div
          className="pointer-events-none absolute left-2 top-1.5 z-10 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-x-3 gap-y-0.5 text-2xs"
          aria-live="off"
        >
          <span className="font-semibold text-terminal-text">{symbol || '—'}</span>
          <span className="uppercase tracking-wide text-terminal-muted">{timeframe}</span>
          <span className="text-terminal-muted">{candleStamp(displayCandle.timestamp)}</span>
          <span className={tone}>O {formatNumber(displayCandle.open, digits)}</span>
          <span className={tone}>H {formatNumber(displayCandle.high, digits)}</span>
          <span className={tone}>L {formatNumber(displayCandle.low, digits)}</span>
          <span className={tone}>C {formatNumber(displayCandle.close, digits)}</span>
          <span className="text-terminal-muted">
            Vol {formatNumber(displayCandle.volume, 0)}
          </span>
        </div>
      ) : null}
      {candles.length === 0 ? (
        <div className="absolute inset-0 flex items-center justify-center bg-terminal-bg/80">
          <EmptyState title="No candles available" icon="chart" />
        </div>
      ) : null}
    </div>
  );
}
