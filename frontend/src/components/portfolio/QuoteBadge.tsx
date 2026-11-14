import type { Quote } from '../../types/api';
import { quoteLabel, quoteTone } from '../../utils/quotes';
import { Badge } from '../common/Badge';

export function QuoteBadge({
  quote,
  className,
}: {
  quote: Quote | null | undefined;
  className?: string;
}) {
  const title = quote
    ? [
        quote.provider,
        quote.quote_time ? `Quote ${quote.quote_time}` : null,
        quote.error,
      ]
        .filter(Boolean)
        .join(' · ')
    : 'No quote';
  return (
    <Badge tone={quoteTone(quote)} dot className={className} title={title}>
      {quoteLabel(quote)}
    </Badge>
  );
}
