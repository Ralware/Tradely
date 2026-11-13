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
import type { Candle, IndicatorSeriesRow, IndicatorValues } from '../../types/api';
import { EmptyState } from '../common/States';

export interface OverlayToggles {
  sma: boolean;
  ema: boolean;
  bollinger: boolean;
}

interface PriceChartProps {
  candles: Candle[];
  series: IndicatorSeriesRow[] | null;
  latest: IndicatorValues | null;
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
      { field: 'sma_20', title: 'SMA 20', color: '#f0b95c' },
      { field: 'sma_50', title: 'SMA 50', color: '#7c9cff' },
      { field: 'sma_200', title: 'SMA 200', color: '#c084fc' },
    ],
  },
  {
    key: 'ema',
    lines: [
      { field: 'ema_20', title: 'EMA 20', color: '#2fd18a' },
      { field: 'ema_50', title: 'EMA 50', color: '#38bdf8' },
      { field: 'ema_200', title: 'EMA 200', color: '#f472b6' },
    ],
  },
  {
    key: 'bollinger',
    lines: [
      { field: 'bb_upper', title: 'BB upper', color: '#64748b', dashed: true },
      { field: 'bb_mid', title: 'BB mid', color: '#94a3b8', dashed: true },
      { field: 'bb_lower', title: 'BB lower', color: '#64748b', dashed: true },
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
  latest,
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
        background: { type: ColorType.Solid, color: '#0f1520' },
        textColor: '#8b9bb0',
        fontSize: 11,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#182230' },
        horzLines: { color: '#182230' },
      },
      rightPriceScale: { borderColor: '#1f2a37', scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderColor: '#1f2a37',
        timeVisible: intraday,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#33445c', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#22304a' },
        horzLine: { color: '#33445c', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#22304a' },
      },
    });

    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#2fd18a',
      downColor: '#ff6b6b',
      borderVisible: false,
      wickUpColor: '#2fd18a',
      wickDownColor: '#ff6b6b',
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
              candle.close >= candle.open ? 'rgba(47, 209, 138, 0.28)' : 'rgba(255, 107, 107, 0.28)',
          },
        ];
      }),
    );

    if (latest) {
      for (const group of overlayGroups) {
        if (!overlays[group.key]) {
          continue;
        }
        for (const line of group.lines) {
          const price = numeric(latest[line.field]);
          if (price === null || price <= 0) {
            continue;
          }
          candleSeries.createPriceLine({
            price,
            color: line.color,
            lineWidth: 1,
            lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
            axisLabelVisible: true,
            title: line.title,
          });
        }
      }
    }

    let paneIndex = 1;

    if (showRsi && series && series.length > 0) {
      const rsiSeries = chart.addSeries(
        LineSeries,
        {
          color: '#c084fc',
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
          color: '#33445c',
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
            { time, value, color: value >= 0 ? 'rgba(47, 209, 138, 0.5)' : 'rgba(255, 107, 107, 0.5)' },
          ];
        }),
      );

      const macdLine = chart.addSeries(
        LineSeries,
        { color: '#7c9cff', lineWidth: 2, priceLineVisible: false, lastValueVisible: false },
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
        { color: '#f0b95c', lineWidth: 1, priceLineVisible: false, lastValueVisible: false },
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
  }, [candles, series, latest, overlays, showRsi, showMacd, intraday]);

  if (candles.length === 0) {
    return <EmptyState title="No candles available" icon="chart" />;
  }

  return <div ref={containerRef} style={{ height }} className="w-full" aria-label="Price chart" />;
}
