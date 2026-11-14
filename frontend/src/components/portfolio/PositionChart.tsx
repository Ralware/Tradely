import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type UTCTimestamp,
} from 'lightweight-charts';
import type { Candle, Transaction } from '../../types/api';
import { EmptyState } from '../common/States';

function toSeconds(timestamp: string): UTCTimestamp | null {
  const millis = Date.parse(timestamp);
  if (Number.isNaN(millis)) {
    return null;
  }
  return Math.floor(millis / 1000) as UTCTimestamp;
}

function snapToCandle(timestamp: string, candleTimes: UTCTimestamp[]): UTCTimestamp | null {
  const target = toSeconds(timestamp);
  if (target === null || candleTimes.length === 0) {
    return null;
  }
  let candidate = candleTimes[0];
  for (const time of candleTimes) {
    if (time <= target) {
      candidate = time;
    } else {
      break;
    }
  }
  return candidate;
}

export function PositionChart({
  candles,
  purchases,
  sales,
  averageCost,
  currentPrice,
  height = 320,
}: {
  candles: Candle[];
  purchases: Transaction[];
  sales: Transaction[];
  averageCost: number;
  currentPrice: number | null;
  height?: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = containerRef.current;
    if (!element || candles.length === 0) {
      return;
    }

    const chart: IChartApi = createChart(element, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#0e1012' },
        textColor: '#8b909a',
        fontSize: 11,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#1a1d22' },
        horzLines: { color: '#1a1d22' },
      },
      rightPriceScale: { borderColor: '#24272e', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: {
        borderColor: '#24272e',
        timeVisible: false,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#20242b' },
        horzLine: { color: '#3a3f4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#20242b' },
      },
    });

    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      priceLineVisible: false,
    });

    const candleData = candles.flatMap((candle) => {
      const time = toSeconds(candle.timestamp);
      if (time === null) {
        return [];
      }
      return [{
        time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      }];
    });
    candleSeries.setData(candleData);
    const candleTimes = candleData.map((item) => item.time);

    if (averageCost > 0) {
      candleSeries.createPriceLine({
        price: averageCost,
        color: '#d6a45a',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Average Cost',
      });
    }
    if (currentPrice !== null && currentPrice > 0) {
      candleSeries.createPriceLine({
        price: currentPrice,
        color: '#2f6feb',
        lineWidth: 1,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Current',
      });
    }

    const purchasePrices = [...new Set(purchases.map((item) => item.price))]
      .filter((price) => Number.isFinite(price) && price > 0)
      .slice(-6);
    for (const price of purchasePrices) {
      candleSeries.createPriceLine({
        price,
        color: '#3a3f4a',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: 'Buy',
      });
    }

    const markers: SeriesMarker<UTCTimestamp>[] = [];
    for (const purchase of purchases) {
      const time = snapToCandle(purchase.trade_time, candleTimes);
      if (time === null) {
        continue;
      }
      markers.push({
        time,
        position: 'belowBar',
        color: '#26a69a',
        shape: 'arrowUp',
        text: `B ${purchase.quantity}`,
      });
    }
    for (const sale of sales) {
      const time = snapToCandle(sale.trade_time, candleTimes);
      if (time === null) {
        continue;
      }
      markers.push({
        time,
        position: 'aboveBar',
        color: '#ef5350',
        shape: 'arrowDown',
        text: `S ${sale.quantity}`,
      });
    }
    markers.sort((left, right) => left.time - right.time);
    if (markers.length > 0) {
      createSeriesMarkers(candleSeries, markers);
    }

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
    };
  }, [candles, purchases, sales, averageCost, currentPrice]);

  if (candles.length === 0) {
    return <EmptyState title="No Price History" description="Candles are unavailable for this instrument." icon="chart" />;
  }

  return <div ref={containerRef} style={{ height }} className="w-full" aria-label="Position price chart" />;
}
