import { useId, useMemo, useState } from 'react';
import type { PointerEvent } from 'react';
import { clamp } from '../../utils/format';
import { EmptyState } from '../common/States';

export interface TimeSeriesPoint {
  timestamp: string;
  value: number;
}

interface TimeSeriesChartProps {
  points: TimeSeriesPoint[];
  height?: number;
  color?: string;
  baseline?: number;
  valueFormatter?: (value: number) => string;
  ariaLabel?: string;
}

function shortDate(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return timestamp;
  }
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
}

export function TimeSeriesChart({
  points,
  height = 220,
  color = '#2f6feb',
  baseline,
  valueFormatter = (value) => value.toFixed(2),
  ariaLabel = 'Time series chart',
}: TimeSeriesChartProps) {
  const rawId = useId();
  const gradientId = `grad-${rawId.replace(/[^a-zA-Z0-9]/g, '')}`;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const geometry = useMemo(() => {
    const valid = points.filter((point) => Number.isFinite(point.value));
    if (valid.length === 0) {
      return null;
    }

    const values = valid.map((point) => point.value);
    let lo = Math.min(...values);
    let hi = Math.max(...values);
    if (baseline !== undefined) {
      lo = Math.min(lo, baseline);
      hi = Math.max(hi, baseline);
    }
    if (hi === lo) {
      hi += 1;
      lo -= 1;
    }
    const padding = (hi - lo) * 0.08;
    const min = lo - padding;
    const max = hi + padding;
    const span = max - min || 1;

    const x = (index: number) => (valid.length === 1 ? 0 : (index / (valid.length - 1)) * 100);
    const y = (value: number) => (1 - (value - min) / span) * 100;

    const line = valid
      .map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index).toFixed(3)},${y(point.value).toFixed(3)}`)
      .join(' ');

    const closeY = baseline === undefined ? 100 : y(baseline);
    const area = `M${x(0).toFixed(3)},${closeY.toFixed(3)} ${line.replace(/^M/, 'L')} L${x(
      valid.length - 1,
    ).toFixed(3)},${closeY.toFixed(3)} Z`;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => ({
      position: fraction * 100,
      value: max - fraction * span,
    }));

    return { valid, line, area, ticks, x, y, min, max };
  }, [points, baseline]);

  if (!geometry) {
    return <EmptyState title="No series data" icon="chart" />;
  }

  const { valid, line, area, ticks, x, y } = geometry;
  const hovered = hoverIndex === null ? null : valid[hoverIndex];
  const last = valid[valid.length - 1];

  function handleMove(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0) {
      return;
    }
    const fraction = clamp((event.clientX - rect.left) / rect.width, 0, 1);
    setHoverIndex(Math.round(fraction * (valid.length - 1)));
  }

  return (
    <div
      className="relative w-full select-none"
      style={{ height }}
      role="img"
      aria-label={ariaLabel}
      onPointerMove={handleMove}
      onPointerLeave={() => setHoverIndex(null)}
    >
      <div className="absolute inset-y-0 left-0 right-14">
        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="h-full w-full overflow-visible"
        >
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity="0.32" />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </linearGradient>
          </defs>

          {ticks.map((tick) => (
            <line
              key={tick.position}
              x1="0"
              x2="100"
              y1={tick.position}
              y2={tick.position}
              stroke="#1a1d22"
              strokeWidth="1"
              vectorEffect="non-scaling-stroke"
            />
          ))}

          {baseline !== undefined ? (
            <line
              x1="0"
              x2="100"
              y1={y(baseline)}
              y2={y(baseline)}
              stroke="#3a3f4a"
              strokeWidth="1"
              strokeDasharray="3 3"
              vectorEffect="non-scaling-stroke"
            />
          ) : null}

          <path d={area} fill={`url(#${gradientId})`} />
          <path
            d={line}
            fill="none"
            stroke={color}
            strokeWidth="1.6"
            vectorEffect="non-scaling-stroke"
            strokeLinejoin="round"
          />

          {hovered ? (
            <>
              <line
                x1={x(hoverIndex ?? 0)}
                x2={x(hoverIndex ?? 0)}
                y1="0"
                y2="100"
                stroke="#3a3f4a"
                strokeWidth="1"
                strokeDasharray="3 3"
                vectorEffect="non-scaling-stroke"
              />
              <circle
                cx={x(hoverIndex ?? 0)}
                cy={y(hovered.value)}
                r="1.6"
                fill={color}
                vectorEffect="non-scaling-stroke"
              />
            </>
          ) : null}
        </svg>

        <div className="pointer-events-none absolute inset-x-0 top-0 flex justify-end">
          <span className="num rounded-sm border border-terminal-border bg-terminal-panelAlt/90 px-2 py-0.5 text-2xs text-terminal-text">
            {hovered
              ? `${shortDate(hovered.timestamp)} · ${valueFormatter(hovered.value)}`
              : `${shortDate(last.timestamp)} · ${valueFormatter(last.value)}`}
          </span>
        </div>
      </div>

      <div className="pointer-events-none absolute inset-y-0 right-0 w-14">
        {ticks.map((tick) => (
          <span
            key={tick.position}
            className="num absolute right-0 -translate-y-1/2 text-2xs text-terminal-muted"
            style={{ top: `${tick.position}%` }}
          >
            {valueFormatter(tick.value)}
          </span>
        ))}
      </div>

      <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-between pr-14 text-2xs text-terminal-muted">
        <span>{shortDate(valid[0].timestamp)}</span>
        <span>{shortDate(valid[Math.floor(valid.length / 2)].timestamp)}</span>
        <span>{shortDate(last.timestamp)}</span>
      </div>
    </div>
  );
}
