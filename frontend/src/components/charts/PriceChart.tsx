import { useEffect, useRef } from 'react';
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
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, IndicatorSeriesRow } from '../../types/api';
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

export function PriceChart({
  candles,
  series,
  overlays,
  showRsi,
  showMacd,
  intraday = false,
  height = 380,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || candles.length === 0) {
      return;
    }

    const chart: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#000000' },
        textColor: '#8b909a',
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
        vertLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#000000' },
        horzLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#000000' },
      },
    });

    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#2f6feb',
      downColor: '#ffffff',
      borderVisible: false,
      wickUpColor: '#2f6feb',
      wickDownColor: '#ffffff',
      priceLineVisible: false,
    });

    const candleData = candles.flatMap((candle) => {
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
    candleSeries.setData(candleData);

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
    volumeSeries.setData(
      candles.flatMap((candle) => {
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
      }),
    );

    if (series && series.length > 0) {
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
          overlaySeries.setData(
            series.flatMap((row) => {
              const time = toSeconds(row.timestamp);
              const value = numeric(row[line.field]);
              return time === null || value === null ? [] : [{ time, value }];
            }),
          );
        }
      }
    }

    let paneIndex = 1;

    if (showRsi && series && series.length > 0) {
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
      rsiSeries.setData(
        series.flatMap((row) => {
          const time = toSeconds(row.timestamp);
          const value = numeric(row.rsi_14);
          return time === null || value === null ? [] : [{ time, value }];
        }),
      );
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
      paneIndex += 1;
    }

    if (showMacd && series && series.length > 0) {
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
            { time, value, color: value >= 0 ? 'rgba(38, 166, 154, 0.5)' : 'rgba(239, 83, 80, 0.5)' },
          ];
        }),
      );

      const macdLine = chart.addSeries(
        LineSeries,
        { color: '#2f6feb', lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      macdLine.setData(
        series.flatMap((row) => {
          const time = toSeconds(row.timestamp);
          const value = numeric(row.macd);
          return time === null || value === null ? [] : [{ time, value }];
        }),
      );

      const signalLine = chart.addSeries(
        LineSeries,
        { color: '#d6a45a', lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
        paneIndex,
      );
      signalLine.setData(
        series.flatMap((row) => {
          const time = toSeconds(row.timestamp);
          const value = numeric(row.macd_signal);
          return time === null || value === null ? [] : [{ time, value }];
        }),
      );

      chart.panes()[paneIndex]?.setHeight(120);
      paneIndex += 1;
    }

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [candles, series, overlays, showRsi, showMacd, intraday]);

  if (candles.length === 0) {
    return <EmptyState title="No candles available" icon="chart" />;
  }

  return <div ref={containerRef} style={{ height }} className="w-full" aria-label="Price chart" />;
}
