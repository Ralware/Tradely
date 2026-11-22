import type { TechnicalCounts } from '../../types/api';

type TechnicalSummaryGroup = {
  oscillators: TechnicalCounts;
  moving_averages: TechnicalCounts;
  overall: TechnicalCounts;
};

type TechnicalDistributionProps =
  | { label: string; summary: TechnicalCounts }
  | { label?: never; summary: TechnicalSummaryGroup };

export function TechnicalDistribution({ label, summary }: TechnicalDistributionProps) {
  const isGroupSummary = 'overall' in summary;
  const groups = isGroupSummary
    ? [
        { label: 'Moving Averages', summary: summary.moving_averages },
        { label: 'Oscillators', summary: summary.oscillators },
        { label: 'Overall', summary: summary.overall },
      ]
    : [{ label: label ?? 'Technical', summary }];

  return (
    <div className={isGroupSummary ? 'tv-rating-counts-groups' : undefined}>
      {groups.map((group) => (
        <div key={group.label} className={isGroupSummary ? 'tv-rating-count-group' : undefined}>
          {isGroupSummary ? <span className="tv-rating-group-title">{group.label}</span> : null}
          <div
            className="tv-rating-counts"
            aria-label={`${group.label}: ${group.summary.sell} sell, ${group.summary.neutral} neutral, ${group.summary.buy} buy`}
            title={`${group.summary.available} of ${group.summary.total} indicators available; ${group.summary.unavailable} unavailable`}
          >
            <div className="tv-rating-count tv-rating-count-sell">
              <span>Sell</span>
              <strong className="num">{group.summary.sell}</strong>
            </div>
            <div className="tv-rating-count tv-rating-count-neutral">
              <span>Neutral</span>
              <strong className="num">{group.summary.neutral}</strong>
            </div>
            <div className="tv-rating-count tv-rating-count-buy">
              <span>Buy</span>
              <strong className="num">{group.summary.buy}</strong>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
