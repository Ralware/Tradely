import type { Candle } from "../../types/api";
import { formatDateTime, formatNumber } from "../../utils/format";
import { EmptyState } from "../common/States";

export function CandleTable({
  candles,
  limit = 30,
  pricePrecision = null,
}: {
  candles: Candle[];
  limit?: number;
  pricePrecision?: number | null;
}) {
  if (candles.length === 0) {
    return <EmptyState title="No Candle History" icon="chart" />;
  }

  const rows = candles.slice(-limit).reverse();
  const digits =
    typeof pricePrecision === 'number' && Number.isFinite(pricePrecision)
      ? Math.max(0, Math.min(12, Math.trunc(pricePrecision)))
      : null;
  // Metadata-first, with the value's own magnitude as the last resort so a
  // sub-dollar instrument is never rounded to two decimals.
  const precisionFor = (value: number): number => {
    if (digits !== null) return digits;
    if (Math.abs(value) >= 1000) return 2;
    if (Math.abs(value) >= 1) return 4;
    if (Math.abs(value) >= 0.01) return 6;
    return 8;
  };

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Time</th>
            <th className="py-1.5 pr-3 text-right font-medium">Open</th>
            <th className="py-1.5 pr-3 text-right font-medium">High</th>
            <th className="py-1.5 pr-3 text-right font-medium">Low</th>
            <th className="py-1.5 pr-3 text-right font-medium">Close</th>
            <th className="py-1.5 text-right font-medium">Volume</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((candle) => (
            <tr
              key={candle.timestamp}
              className="border-b border-terminal-borderSoft last:border-0 hover:bg-white/[0.02]"
            >
              <td className="num py-1.5 pr-3 text-terminal-muted">
                {formatDateTime(candle.timestamp)}
              </td>
              <td className="num py-1.5 pr-3 text-right text-terminal-text">
                {formatNumber(candle.open, precisionFor(candle.open))}
              </td>
              <td className="num py-1.5 pr-3 text-right text-terminal-text">
                {formatNumber(candle.high, precisionFor(candle.high))}
              </td>
              <td className="num py-1.5 pr-3 text-right text-terminal-text">
                {formatNumber(candle.low, precisionFor(candle.low))}
              </td>
              <td className="num py-1.5 pr-3 text-right font-medium text-terminal-text">
                {formatNumber(candle.close, precisionFor(candle.close))}
              </td>
              <td className="num py-1.5 text-right text-terminal-muted">
                {formatNumber(candle.volume, 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
