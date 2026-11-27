import { useMemo } from 'react';
import { cn } from '../../utils/format';

export function Sparkline({
  values,
  className,
  height = 36,
}: {
  values: number[];
  className?: string;
  height?: number;
}) {
  const path = useMemo(() => {
    const finite = values.filter((value) => Number.isFinite(value));
    if (finite.length < 2) {
      return null;
    }
    const minimum = Math.min(...finite);
    const maximum = Math.max(...finite);
    const span = maximum - minimum || 1;
    const width = 240;
    const step = width / (finite.length - 1);
    const points = finite.map((value, index) => {
      const x = index * step;
      const y = height - ((value - minimum) / span) * (height - 6) - 3;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    const rising = finite[finite.length - 1] >= finite[0];
    const line = `M ${points.join(' L ')}`;
    return { line, rising };
  }, [values, height]);

  if (!path) {
    return (
      <div
        className={cn('flex items-center justify-center text-2xs text-terminal-muted', className)}
        style={{ height }}
      >
        —
      </div>
    );
  }

  const color = path.rising ? '#22c55e' : '#f04444';

  return (
    <svg
      viewBox={`0 0 240 ${height}`}
      preserveAspectRatio="none"
      className={cn('w-full', className)}
      style={{ height }}
      aria-hidden="true"
    >
      <path
        d={path.line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
