import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  TickMarkType,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, IndicatorSeriesRow } from '../../types/api';
import { isPlausibleLiveCandle as isPlausibleCandle, replaceFormingCandle } from './liveCandleUtils';
import { getCachedLiveCandles, setCachedLiveCandles } from './liveCandleStore';
import { analyticsViewStore } from '../../services/analyticsViewStore';
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
  instrumentId?: string;
  timeframe?: string;
  symbol?: string;
  pricePrecision?: number | null;
  priceMinMove?: number | null;
  /** Provider's current in-progress candle, kept separate from completed analytics bars. */
  formingCandle?: Candle | null;
  /** Current-price marker only; never merged into candle OHLCV. */
  livePrice?: number | null;
  height?: number;
}

const CHART_COLORS = {
  background: '#000000',
  surface: '#000000',
  border: '#1C1C1C',
  grid: '#141414',
  text: '#929292',
  accent: '#1685FF',
  candleUp: '#1685FF',
  candleDown: '#F5F5F5',
  candleNeutral: '#929292',
  sell: '#F04452',
} as const;

const overlayGroups: Array<{
  key: keyof OverlayToggles;
  lines: Array<{ field: string; title: string; color: string; dashed?: boolean }>;
}> = [
  {
    key: 'sma',
    lines: [
      { field: 'sma_20', title: 'SMA 20', color: '#8EBEF5' },
      { field: 'sma_50', title: 'SMA 50', color: '#1685FF' },
      { field: 'sma_100', title: 'SMA 100', color: '#929292' },
      { field: 'sma_200', title: 'SMA 200', color: '#b9a8ff' },
    ],
  },
  {
    key: 'ema',
    lines: [
      { field: 'ema_20', title: 'EMA 20', color: '#6DB2FF' },
      { field: 'ema_50', title: 'EMA 50', color: '#1685FF' },
      { field: 'ema_100', title: 'EMA 100', color: '#f2c76e' },
      { field: 'ema_200', title: 'EMA 200', color: '#ff9dcc' },
    ],
  },
  {
    key: 'bollinger',
    lines: [
      { field: 'bb_upper', title: 'BB Upper', color: '#c1c1c1', dashed: true },
      { field: 'bb_mid', title: 'BB Mid', color: '#929292', dashed: true },
      { field: 'bb_lower', title: 'BB Lower', color: '#c1c1c1', dashed: true },
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
    const color = candle.close > candle.open
      ? CHART_COLORS.candleUp
      : candle.close < candle.open
        ? CHART_COLORS.candleDown
        : CHART_COLORS.candleNeutral;
    return [
      {
        time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        color,
        borderColor: color,
        wickColor: color,
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
          candle.close > candle.open
            ? 'rgba(38, 139, 255, 0.28)'
            : candle.close < candle.open
              ? 'rgba(242, 242, 242, 0.28)'
              : 'rgba(146, 146, 146, 0.28)',
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

const IST_TIME_ZONE = 'Asia/Kolkata';
const IST_YEAR_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  year: 'numeric',
});
const IST_MONTH_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  month: 'short',
});
const IST_DAY_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  day: '2-digit',
});
const IST_TIME_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});
const IST_TIME_SECONDS_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});
const IST_STAMP_FORMAT = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST_TIME_ZONE,
  dateStyle: 'medium',
  timeStyle: 'short',
});

function timeToDate(time: Time): Date | null {
  if (typeof time === 'number') {
    return new Date(time * 1000);
  }
  if (typeof time === 'string') {
    const parsed = Date.parse(time);
    return Number.isNaN(parsed) ? null : new Date(parsed);
  }
  if (typeof time === 'object' && time !== null) {
    return new Date(Date.UTC(time.year, time.month - 1, time.day));
  }
  return null;
}

function istTickMark(time: Time, tickMarkType: TickMarkType): string {
  const date = timeToDate(time);
  if (!date) return '';
  switch (tickMarkType) {
    case TickMarkType.Year:
      return IST_YEAR_FORMAT.format(date);
    case TickMarkType.Month:
      return IST_MONTH_FORMAT.format(date);
    case TickMarkType.DayOfMonth:
      return IST_DAY_FORMAT.format(date);
    case TickMarkType.Time:
      return IST_TIME_FORMAT.format(date);
    case TickMarkType.TimeWithSeconds:
      return IST_TIME_SECONDS_FORMAT.format(date);
    default:
      return IST_STAMP_FORMAT.format(date);
  }
}

function istTimeLabel(time: Time): string {
  const date = timeToDate(time);
  return date ? `${IST_STAMP_FORMAT.format(date)} IST` : '';
}

function candleStamp(timestamp: string): string {
  const parsed = Date.parse(timestamp);
  if (Number.isNaN(parsed)) return timestamp;
  return `${IST_STAMP_FORMAT.format(new Date(parsed))} IST`;
}

function indicatorValueAt(series: IndicatorSeriesRow[] | null, field: string, timestamp: string | null): number | null {
  if (!series || series.length === 0) return null;
  const targetTime = timestamp === null ? null : toSeconds(timestamp);
  const row = timestamp
    ? series.find((item) => toSeconds(item.timestamp) === targetTime)
    : series[series.length - 1];
  return numeric(row?.[field]);
}

function indicatorDigits(field: string, priceDigits: number): number {
  if (field === 'rsi_14') return 1;
  if (field === 'macd' || field === 'macd_signal' || field === 'macd_hist') return 6;
  return priceDigits;
}

export function PriceChart({
  candles,
  series,
  overlays,
  showRsi,
  showMacd,
  intraday = false,
  instrumentId = '',
  timeframe = '1d',
  symbol = '',
  pricePrecision = null,
  priceMinMove = null,
  formingCandle = null,
  livePrice = null,
  height = 380,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const livePriceLineRef = useRef<IPriceLine | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const overlaySeriesRef = useRef<ISeriesApi<'Line'>[]>([]);
  const indicatorSeriesRef = useRef<Array<ISeriesApi<'Line'> | ISeriesApi<'Histogram'>>>([]);
  const activeTimeframeRef = useRef<string | null>(null);
  const activeSymbolRef = useRef<string | null>(null);
  const timeRangeAnimationRef = useRef<number | null>(null);
  const identityRef = useRef<string>('');
  identityRef.current = instrumentId || symbol;
  const timeframeRef = useRef(timeframe);
  timeframeRef.current = timeframe;
  // Hover time is kept in React state so the HTML legend re-renders on
  // crosshair movement; the values themselves always come from `candles`.
  const [hoveredTime, setHoveredTime] = useState<UTCTimestamp | null>(null);
  const chartIdentity = `${instrumentId || symbol}\u0000${timeframe}`;
  const [liveCandleState, setLiveCandleState] = useState<{ key: string; candles: Candle[] } | null>(() => {
    const cached = getCachedLiveCandles(chartIdentity);
    return cached ? { key: chartIdentity, candles: cached } : null;
  });

  useEffect(() => {
    const cached = getCachedLiveCandles(chartIdentity);
    setLiveCandleState(cached ? { key: chartIdentity, candles: cached } : null);
  }, [chartIdentity]);

  useEffect(() => {
    if (!liveCandleState || !liveCandleState.candles.length) return;
    setCachedLiveCandles(liveCandleState.key, liveCandleState.candles);
  }, [liveCandleState]);

  useEffect(() => {
    const referenceClose = candles[candles.length - 1]?.close;
    const validProviderCandle = formingCandle && isPlausibleCandle(formingCandle, referenceClose)
      ? formingCandle
      : null;
    if (!validProviderCandle) return;
    const timestampSeconds = toSeconds(validProviderCandle.timestamp);
    if (timestampSeconds === null) return;
    const latestCompletedSeconds = candles.length
      ? toSeconds(candles[candles.length - 1].timestamp)
      : null;
    // Some analytics snapshots include a bar at the same opening time as the
    // provider's forming candle. In that case the API snapshot is authoritative
    // and must replace it; only an older timestamp is stale.
    if (latestCompletedSeconds !== null && timestampSeconds < latestCompletedSeconds) return;

    setLiveCandleState((previousState) => {
      const liveBars = previousState?.key === chartIdentity ? previousState.candles : [];
      const newestCachedSeconds = liveBars.length ? toSeconds(liveBars[liveBars.length - 1].timestamp) : null;
      if (newestCachedSeconds !== null && timestampSeconds < newestCachedSeconds) return previousState;
      const nextBars = replaceFormingCandle(liveBars, validProviderCandle);
      if (nextBars.length === liveBars.length
        && nextBars.every((bar, index) => bar === liveBars[index])) return previousState;
      return { key: chartIdentity, candles: nextBars };
    });
  }, [candles, chartIdentity, formingCandle]);

  // The current in-progress bar is replaced by each provider OHLCV snapshot;
  // quote ticks are never used to synthesize or mutate its candle values.
  const chartCandles = useMemo(() => {
    const byTime = new Map<number, Candle>();
    for (const candle of candles) {
      const time = toSeconds(candle.timestamp);
      if (time !== null) byTime.set(time, candle);
    }
    const liveBars = liveCandleState?.key === chartIdentity ? liveCandleState.candles : [];
    const referenceClose = candles[candles.length - 1]?.close;
    const validFormingCandle = formingCandle && isPlausibleCandle(formingCandle, referenceClose)
      ? formingCandle
      : null;
    const displayBars = [...liveBars];
    let activeBarTime = liveBars.length ? toSeconds(liveBars[liveBars.length - 1].timestamp) : null;
    if (validFormingCandle) {
      const formingTime = toSeconds(validFormingCandle.timestamp);
      const latestCompletedTime = candles.length ? toSeconds(candles[candles.length - 1].timestamp) : null;
      if (formingTime !== null && (latestCompletedTime === null || formingTime >= latestCompletedTime)) {
        displayBars.push(validFormingCandle);
        activeBarTime = formingTime;
      }
    }
    for (const candle of displayBars) {
      const time = toSeconds(candle.timestamp);
      const isActiveBar = time !== null && time === activeBarTime;
      if (time !== null && Number.isFinite(candle.close) && (isActiveBar || !byTime.has(time))) {
        byTime.set(time, candle);
      }
    }
    return [...byTime.entries()].sort(([left], [right]) => left - right).map(([, candle]) => candle);
  }, [candles, formingCandle, liveCandleState, chartIdentity]);

  const digits =
    typeof pricePrecision === 'number' && Number.isFinite(pricePrecision)
      ? Math.max(0, Math.min(12, Math.trunc(pricePrecision)))
      : fallbackPrecision(
        chartCandles.length ? chartCandles[chartCandles.length - 1].close : null,
      );
  const minMove =
    typeof priceMinMove === 'number' && Number.isFinite(priceMinMove) && priceMinMove > 0
      ? priceMinMove
      : 10 ** -digits;
  const latestCandle = chartCandles.length ? chartCandles[chartCandles.length - 1] : null;
  const hoveredCandle =
    hoveredTime === null
      ? null
      : chartCandles.find((candle) => toSeconds(candle.timestamp) === hoveredTime) ?? null;
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
        background: { type: ColorType.Solid, color: CHART_COLORS.background },
        textColor: CHART_COLORS.text,
        fontSize: 11,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: CHART_COLORS.grid },
        horzLines: { color: CHART_COLORS.grid },
      },
      rightPriceScale: { borderColor: CHART_COLORS.border, scaleMargins: { top: 0.08, bottom: 0.08 } },
      localization: {
        timeFormatter: istTimeLabel,
      },
      timeScale: {
        borderColor: CHART_COLORS.border,
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: 4,
        tickMarkFormatter: istTickMark,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#4a4a4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: CHART_COLORS.surface },
        horzLine: { color: '#4a4a4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: CHART_COLORS.surface },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: CHART_COLORS.candleUp,
      downColor: CHART_COLORS.candleDown,
      borderVisible: false,
      wickUpColor: CHART_COLORS.candleUp,
      wickDownColor: CHART_COLORS.candleDown,
      priceLineVisible: false,
      lastValueVisible: false,
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

    // Persist user zoom/scroll per instrument + timeframe so remounting the
    // workspace (navigation) restores the exact same viewport.
    let persistFrame: number | null = null;
    const persistVisibleRange = () => {
      if (persistFrame !== null) return;
      persistFrame = requestAnimationFrame(() => {
        persistFrame = null;
        const range = chartRef.current?.timeScale().getVisibleLogicalRange();
        const identity = identityRef.current;
        if (!range || !identity) return;
        analyticsViewStore.setRange(identity, timeframeRef.current, {
          from: range.from,
          to: range.to,
        });
      });
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(persistVisibleRange);

    return () => {
      if (timeRangeAnimationRef.current !== null) {
        cancelAnimationFrame(timeRangeAnimationRef.current);
        timeRangeAnimationRef.current = null;
      }
      if (persistFrame !== null) {
        cancelAnimationFrame(persistFrame);
        persistFrame = null;
      }
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(persistVisibleRange);
      chart.unsubscribeCrosshairMove(handleCrosshair);
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      livePriceLineRef.current = null;
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
    const candleSeries = candleSeriesRef.current;
    if (!candleSeries) return;
    const currentPrice = livePrice ?? latestCandle?.close;
    if (typeof currentPrice !== 'number' || !Number.isFinite(currentPrice) || currentPrice <= 0) {
      if (livePriceLineRef.current) {
        candleSeries.removePriceLine(livePriceLineRef.current);
        livePriceLineRef.current = null;
      }
      return;
    }
    if (livePriceLineRef.current) {
      livePriceLineRef.current.applyOptions({ price: currentPrice });
      return;
    }
    livePriceLineRef.current = candleSeries.createPriceLine({
      price: currentPrice,
      color: CHART_COLORS.accent,
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      axisLabelVisible: true,
      title: '',
    });
  }, [livePrice, latestCandle, digits]);

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
    if (!chart || !candleSeries || !volumeSeries || chartCandles.length === 0) {
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
    const storedRange = analyticsViewStore.getRange(instrumentId || symbol, timeframe);

    candleSeries.setData(candlePoints(chartCandles));
    volumeSeries.setData(volumePoints(chartCandles));

    // A routine refresh appends bars at the same logical indices, so keep the
    // user's zoom and scroll position instead of snapping back to fitContent.
    if (!firstLoad && !timeframeChanged && !symbolChanged) {
      if (previousRange) {
        timeScale.setVisibleLogicalRange(previousRange);
      }
      return;
    }

    // Returning to a previously-viewed instrument/timeframe restores the exact
    // viewport the user left instead of zooming all the way out.
    if (storedRange) {
      timeScale.setVisibleLogicalRange(storedRange);
      return;
    }

    const lastIndex = chartCandles.length - 1;
    timeScale.setVisibleLogicalRange({
      from: Math.max(0, lastIndex - 70),
      to: lastIndex + 4,
    });

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
  }, [chartCandles, instrumentId, timeframe, symbol]);

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
          color: '#b9a8ff',
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
              color: '#4a4a4a',
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
              { time, value, color: value >= 0 ? 'rgba(38, 139, 255, 0.5)' : 'rgba(240, 68, 68, 0.5)' },
          ];
        }),
      );

      const macdLine = chart.addSeries(
        LineSeries,
        { color: CHART_COLORS.accent, lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      macdLine.setData(seriesPoints(series, 'macd'));

      const signalLine = chart.addSeries(
        LineSeries,
        { color: '#f2c76e', lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
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
  const activeIndicatorLines = [
    ...overlayGroups.flatMap((group) => overlays[group.key] ? group.lines : []),
    ...(showRsi ? [{ field: 'rsi_14', title: 'RSI 14', color: '#b9a8ff' }] : []),
    ...(showMacd ? [
      { field: 'macd', title: 'MACD', color: CHART_COLORS.accent },
      { field: 'macd_signal', title: 'Signal', color: '#f2c76e' },
      { field: 'macd_hist', title: 'Histogram', color: CHART_COLORS.sell },
    ] : []),
  ];
  const indicatorTimestamp = displayCandle?.timestamp ?? null;

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
          {activeIndicatorLines.map((line) => (
            <span key={line.field} style={{ color: line.color }}>
              <span className="font-medium">{line.title}</span>{' '}
              <span className="num">
                {formatNumber(
                  indicatorValueAt(series, line.field, indicatorTimestamp),
                  indicatorDigits(line.field, digits),
                )}
              </span>
            </span>
          ))}
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
