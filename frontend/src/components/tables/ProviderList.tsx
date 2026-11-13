import type { ProviderStatus } from '../../types/api';
import { Badge } from '../common/Badge';

export function ProviderList({ providers }: { providers: ProviderStatus[] }) {
  return (
    <ul className="divide-y divide-terminal-borderSoft">
      {providers.map((provider) => (
        <li key={provider.name} className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0">
          <div className="min-w-0">
            <p className="text-xs font-medium text-terminal-text">{provider.name}</p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-terminal-muted">{provider.note}</p>
          </div>
          <Badge tone={provider.configured ? 'positive' : 'warning'}>
            {provider.configured ? 'configured' : 'not configured'}
          </Badge>
        </li>
      ))}
    </ul>
  );
}
