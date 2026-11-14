import type { NewsItem } from '../../types/api';
import { formatDateTime } from '../../utils/format';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/States';

export function NewsList({ items, note }: { items: NewsItem[]; note?: string }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="No News Items"
        description={note ?? 'No provider records returned.'}
        icon="search"
      />
    );
  }

  return (
    <ul className="divide-y divide-terminal-borderSoft">
      {items.map((item) => (
        <li key={item.id} className="py-1.5 first:pt-0 last:pb-0">
          <div className="flex items-start justify-between gap-3">
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-medium text-terminal-text hover:text-terminal-accent"
            >
              {item.title}
            </a>
            {item.official ? <Badge tone="positive">Official</Badge> : null}
          </div>
          {item.summary ? (
            <p className="mt-0.5 line-clamp-2 text-2xs leading-relaxed text-terminal-muted">
              {item.summary}
            </p>
          ) : null}
          <p className="mt-0.5 text-2xs text-terminal-muted">
            {item.publisher ?? item.source} ·{' '}
            {item.published_at ? formatDateTime(item.published_at) : 'Time Unavailable'}
          </p>
        </li>
      ))}
    </ul>
  );
}
