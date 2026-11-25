import type { TechnicalCounts } from '../../types/api';
import { cn } from '../../utils/format';
import { TechnicalDistribution } from './TechnicalDistribution';

interface TechnicalGaugeProps {
  label: string;
  summary: TechnicalCounts;
  size?: 'default' | 'hero';
}

const CX = 158;
const ARC_CY = 158.5;
const NEEDLE_CY = 150.5;
const RADIUS = 151.68;

const SEGMENTS = [
  { from: 178, to: 146, color: '#f04444' },
  { from: 142, to: 110, color: '#8f3535' },
  { from: 106, to: 74, color: '#4a4a4a' },
  { from: 70, to: 38, color: '#1f6fdc' },
  { from: 34, to: 2, color: '#268bff' },
] as const;

function polar(angleDegrees: number, radius: number): { x: number; y: number } {
  const radians = (angleDegrees * Math.PI) / 180;
  return {
    x: CX + radius * Math.cos(radians),
    y: ARC_CY - radius * Math.sin(radians),
  };
}

function arcPath(startAngle: number, endAngle: number): string {
  const start = polar(startAngle, RADIUS);
  const end = polar(endAngle, RADIUS);
  return `M ${start.x.toFixed(3)} ${start.y.toFixed(3)} A ${RADIUS} ${RADIUS} 0 0 1 ${end.x.toFixed(3)} ${end.y.toFixed(3)}`;
}

function actionTone(action: TechnicalCounts['action']): string {
  if (action === 'Strong Buy' || action === 'Buy') return 'tv-rating-action-buy';
  if (action === 'Strong Sell' || action === 'Sell') return 'tv-rating-action-sell';
  return 'tv-rating-action-neutral';
}

function actionLabel(action: TechnicalCounts['action']): string {
  if (action === 'Strong Buy') return 'Strong buy';
  if (action === 'Strong Sell') return 'Strong sell';
  return action;
}

export function TechnicalGauge({ label, summary, size = 'default' }: TechnicalGaugeProps) {
  const score = summary.score === null ? null : Math.max(-1, Math.min(1, summary.score));
  const rotation = score === null ? null : -90 + score * 90;
  const hero = size === 'hero';

  return (
    <div className={cn('tv-rating-gauge', hero && 'tv-rating-gauge-hero')}>
      <div className="tv-rating-gauge-dial">
        <svg
          viewBox="0 0 316 158.5"
          className="tv-rating-gauge-svg"
          role="img"
          aria-label={`${label}: ${actionLabel(summary.action)}; ${summary.available} of ${summary.total} indicators available`}
        >
          {SEGMENTS.map((segment) => (
            <path
              key={segment.from}
              d={arcPath(segment.from, segment.to)}
              className="tv-rating-gauge-segment"
              pathLength={1}
              stroke={segment.color}
              strokeWidth="12.64"
              strokeLinecap="round"
              fill="none"
            />
          ))}
          {rotation !== null ? (
            <g className="tv-rating-needle" transform={`rotate(${rotation} ${CX} ${NEEDLE_CY})`}>
              <path
                d="M 158 142.5 L 268.5 148.9 L 268.5 152.1 L 158 158.5 Z"
                fill="#f5f5f5"
              />
              <circle cx="158" cy="150.5" r="8" fill="#f5f5f5" />
            </g>
          ) : null}
        </svg>
      </div>
      <p className="tv-rating-gauge-title">{label}</p>
      <p className={cn('tv-rating-gauge-action', actionTone(summary.action))}>
        {actionLabel(summary.action)}
      </p>
      <TechnicalDistribution label={label} summary={summary} />
    </div>
  );
}
