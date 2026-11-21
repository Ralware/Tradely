import type { IndicatorValues } from "../../types/api";
import { formatCompact, formatNumber, titleCase } from "../../utils/format";

export function IndicatorTable({
  indicators,
}: {
  indicators: IndicatorValues;
}) {
  const entries = Object.entries(indicators);

  if (entries.length === 0) {
    return <p className="text-xs text-terminal-muted">No Indicator Values</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[380px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Indicator</th>
            <th className="py-1.5 text-right font-medium">Value</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, value]) => (
            <tr
              key={key}
              className="border-b border-terminal-borderSoft last:border-0"
            >
              <td className="py-1.5 pr-3 text-terminal-muted">
                {titleCase(key)}
              </td>
              <td className="num py-1.5 text-right text-terminal-text">
                {value === null
                  ? "—"
                  : key === "obv"
                    ? formatCompact(value)
                    : formatNumber(value, 4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
