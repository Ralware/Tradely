import type { TechnicalCounts } from '../../types/api';
import { cn } from '../../utils/format';

interface TechnicalGaugeProps {
  label: string;
  summary: TechnicalCounts;
  size?: 'default' | 'hero';
}

const CX = 100;
const CY = 100;
const RADIUS = 78;

function polar(angleDegrees: number, radius: number): { x: number; y: number } {
  const radians = (angleDegrees * Math.PI) / 180;
  return {
    x: CX + radius * Math.cos(radians),
    y: CY - radius * Math.sin(radians),
  };
}

function arcPath(startAngle: number, endAngle: number, radius = RADIUS): string {
  const start = polar(startAngle, radius);
  const end = polar(endAngle, radius);
  return `M ${start.x.toFixed(2)} ${start.y.toFixed(2)} A ${radius} ${radius} 0 0 1 ${end.x.toFixed(2)} ${end.y.toFixed(2)}`;
}

export function TechnicalGauge({ label, summary, size = 'default' }: TechnicalGaugeProps) {
  const clamped = Math.max(-1, Math.min(1, summary.score));
  const needleAngle = 180 - ((clamped + 1) / 2) * 180;
  const hero = size === 'hero';

  return (
    <div className={cn('flex flex-col items-center', hero ? 'w-full max-w-[270px]' : 'w-full max-w-[220px]')}>
      <svg
        viewBox="0 0 200 112"
        className={cn('w-full', hero ? 'h-[150px]' : 'h-[118px]')}
        role="img"
        aria-label={`${label}: ${summary.action}`}
      >
        <path d={arcPath(180, 135)} stroke="#ef5350" strokeWidth={7} fill="none" />
        <path d={arcPath(135, 45)} stroke="#4a4f58" strokeWidth={7} fill="none" />
        <path d={arcPath(45, 0)} stroke="#2f6feb" strokeWidth={7} fill="none" />
        <g
          className="transition-transform duration-700 ease-out"
          style={{
            transform: `rotate(${-needleAngle}deg)`,
            transformOrigin: `${CX}px ${CY}px`,
            transformBox: 'view-box',
          }}
        >
          <line
            x1={CX}
            y1={CY}
            x2={CX + 64}
            y2={CY}
            stroke="#c9ced6"
            strokeWidth={2.5}
            strokeLinecap="round"
          />
        </g>
        <circle cx={CX} cy={CY} r={3.6} fill="#c9ced6" />
      </svg>

      <p className="mt-1 text-xs text-terminal-muted">{label}</p>
      <p className={cn('font-semibold leading-tight text-terminal-text', hero ? 'text-[22px]' : 'text-lg')}>
        {summary.action}
      </p>

      <div className="mt-2 grid w-full grid-cols-3 rounded-sm bg-black px-2 py-1.5 text-center">
        <div>
          <p className="text-2xs text-terminal-muted">Sell</p>
          <p className="num text-xs font-medium text-terminal-text">{summary.sell}</p>
        </div>
        <div>
          <p className="text-2xs text-terminal-muted">Neutral</p>
          <p className="num text-xs font-medium text-terminal-text">{summary.neutral}</p>
        </div>
        <div>
          <p className="text-2xs text-terminal-muted">Buy</p>
          <p className="num text-xs font-medium text-terminal-text">{summary.buy}</p>
        </div>
      </div>
    </div>
  );
}
