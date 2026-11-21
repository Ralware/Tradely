import type { Candle } from "../../types/api";
import { formatDateTime, formatNumber } from "../../utils/format";
import { EmptyState } from "../common/States";

export function CandleTable({
  candles,
  limit = 30,
}: {
  candles: Candle[];
  limit?: number;
}) {
  if (candles.length === 0) {
    return <EmptyState title="No Candle History" icon="chart" />;
  }

  const rows = candles.slice(-limit).reverse();

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
                {formatNumber(candle.open, 2)}
              </td>
              <td className="num py-1.5 pr-3 text-right text-terminal-text">
                {formatNumber(candle.high, 2)}
              </td>
              <td className="num py-1.5 pr-3 text-right text-terminal-text">
                {formatNumber(candle.low, 2)}
              </td>
              <td className="num py-1.5 pr-3 text-right font-medium text-terminal-text">
                {formatNumber(candle.close, 2)}
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
