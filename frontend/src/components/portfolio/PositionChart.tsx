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
import type { Candle, PositionDirection, Transaction } from '../../types/api';
import { parseTimestampToEpochSeconds } from '../charts/liveCandleUtils';
import { EmptyState } from '../common/States';

function toSeconds(timestamp: string): UTCTimestamp | null {
  const seconds = parseTimestampToEpochSeconds(timestamp);
  return seconds === null ? null : (seconds as UTCTimestamp);
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
  positionSide = 'LONG',
  averageCost,
  currentPrice,
  height = 320,
}: {
  candles: Candle[];
  purchases: Transaction[];
  sales: Transaction[];
  positionSide?: PositionDirection;
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
        background: { type: ColorType.Solid, color: '#000000' },
        textColor: '#929292',
        fontSize: 11,
        fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: '#111111' },
        horzLines: { color: '#111111' },
      },
      rightPriceScale: { borderColor: '#1d1d1d', scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: {
        borderColor: '#1d1d1d',
        timeVisible: false,
        secondsVisible: false,
        rightOffset: 4,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#4a4a4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#000000' },
        horzLine: { color: '#4a4a4a', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#000000' },
      },
    });

    const candleSeries: ISeriesApi<'Candlestick'> = chart.addSeries(CandlestickSeries, {
      upColor: '#268bff',
      downColor: '#f2f2f2',
      borderVisible: false,
      wickUpColor: '#268bff',
      wickDownColor: '#f2f2f2',
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
        color: candle.close > candle.open ? '#268bff' : candle.close < candle.open ? '#f2f2f2' : '#929292',
        borderColor: candle.close > candle.open ? '#268bff' : candle.close < candle.open ? '#f2f2f2' : '#929292',
        wickColor: candle.close > candle.open ? '#268bff' : candle.close < candle.open ? '#f2f2f2' : '#929292',
      }];
    });
    candleSeries.setData(candleData);
    const candleTimes = candleData.map((item) => item.time);

    if (averageCost > 0) {
      candleSeries.createPriceLine({
        price: averageCost,
        color: '#f59e0b',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: positionSide === 'SHORT' ? 'Average Proceeds' : 'Average Cost',
      });
    }
    if (currentPrice !== null && currentPrice > 0) {
      candleSeries.createPriceLine({
        price: currentPrice,
        color: '#268bff',
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
        color: '#4a4a4a',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        axisLabelVisible: false,
        title: positionSide === 'SHORT' ? 'Short Entry' : 'Buy',
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
        position: positionSide === 'SHORT' ? 'aboveBar' : 'belowBar',
        color: positionSide === 'SHORT' ? '#f04444' : '#268bff',
        shape: positionSide === 'SHORT' ? 'arrowDown' : 'arrowUp',
        text: `${positionSide === 'SHORT' ? 'SS' : 'B'} ${purchase.quantity}`,
      });
    }
    for (const sale of sales) {
      const time = snapToCandle(sale.trade_time, candleTimes);
      if (time === null) {
        continue;
      }
      markers.push({
        time,
        position: positionSide === 'SHORT' ? 'belowBar' : 'aboveBar',
        color: positionSide === 'SHORT' ? '#268bff' : '#f04444',
        shape: positionSide === 'SHORT' ? 'arrowUp' : 'arrowDown',
        text: `${positionSide === 'SHORT' ? 'C' : 'S'} ${sale.quantity}`,
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
  }, [candles, purchases, sales, positionSide, averageCost, currentPrice]);

  if (candles.length === 0) {
    return <EmptyState title="No Price History" description="Candles are unavailable for this instrument." icon="chart" />;
  }

  return <div ref={containerRef} style={{ height }} className="w-full" aria-label="Position price chart" />;
}
