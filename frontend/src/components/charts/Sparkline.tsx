import { useMemo } from 'react';
import { cn } from '../../utils/format';

export function Sparkline({
  values,
  className,
  height = 56,
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
      const y = height - ((value - minimum) / span) * (height - 4) - 2;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    });
    return { line: `M ${points.join(' L ')}`, rising: finite[finite.length - 1] >= finite[0] };
  }, [values, height]);

  if (!path) {
    return (
      <div
        className={cn('flex items-center justify-center text-2xs text-terminal-muted', className)}
        style={{ height }}
      >
        Insufficient History
      </div>
    );
  }

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
        stroke={path.rising ? '#26a69a' : '#ef5350'}
        strokeWidth={1.4}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
