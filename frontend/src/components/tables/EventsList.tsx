import type { CorporateEvent, OfficialSourceLink } from '../../types/api';
import { formatDate } from '../../utils/format';
import { Badge } from '../common/Badge';
import type { BadgeTone } from '../common/Badge';
import { EmptyState, Notice } from '../common/States';

const statusTone: Record<CorporateEvent['status'], BadgeTone> = {
  confirmed: 'positive',
  tentative: 'warning',
  postponed: 'warning',
  cancelled: 'negative',
  historical: 'neutral',
  unverified: 'neutral',
};

export function EventsList({
  events,
  links,
  providerError,
  note,
}: {
  events: CorporateEvent[];
  links: OfficialSourceLink[];
  providerError: string | null;
  note?: string;
}) {
  return (
    <div className="space-y-3">
      {providerError ? (
        <Notice tone="warning">Corporate-action provider: {providerError}</Notice>
      ) : null}

      {events.length === 0 ? (
        <EmptyState
          title="No verified structured events"
          description={note ?? 'Only provider-returned records are shown as events.'}
          icon="info"
        />
      ) : (
        <ul className="divide-y divide-terminal-borderSoft">
          {events.map((event) => (
            <li key={event.id} className="py-2.5 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-medium text-terminal-text">{event.event_type}</span>
                <Badge tone={statusTone[event.status]}>{event.status}</Badge>
                {event.official ? <Badge tone="positive">official</Badge> : null}
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-terminal-muted">
                {event.description}
              </p>
              <p className="mt-1 text-[10px] text-terminal-muted">
                {event.event_date ? formatDate(event.event_date) : 'Date unavailable'} · {event.source}
              </p>
            </li>
          ))}
        </ul>
      )}

      {links.length > 0 ? (
        <div className="border-t border-terminal-borderSoft pt-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
            Verify at the official source
          </p>
          <ul className="space-y-1">
            {links.map((link) => (
              <li key={link.url}>
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] text-terminal-accent hover:underline"
                >
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
