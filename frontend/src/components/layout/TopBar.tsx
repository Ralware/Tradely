import { useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApiStatus } from '../../contexts/ApiStatusContext';
import { cn } from '../../utils/format';
import { Button } from '../common/Button';
import { Icon } from '../common/Icon';
import type { Market } from '../../types/api';

const marketOptions: Array<{ value: Market; label: string }> = [
  { value: 'india', label: 'India' },
  { value: 'global', label: 'Global' },
  { value: 'crypto', label: 'Crypto' },
];

function statusTone(error: string | null, loading: boolean): string {
  if (error) {
    return 'text-terminal-red';
  }
  if (loading) {
    return 'text-terminal-amber';
  }
  return 'text-terminal-green';
}

export function TopBar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const navigate = useNavigate();
  const { health, healthLoading, healthError, refresh } = useApiStatus();
  const [symbol, setSymbol] = useState('');
  const [market, setMarket] = useState<Market>('india');

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = symbol.trim().toUpperCase();
    if (!value) {
      return;
    }
    const exchange = market === 'india' ? 'NSE' : market === 'global' ? 'NASDAQ' : 'BINANCE';
    const path = market === 'crypto' ? '/crypto' : '/stocks';
    navigate(`${path}?symbol=${encodeURIComponent(value)}&market=${market}&exchange=${exchange}`);
    setSymbol('');
  }

  const statusLabel = healthError
    ? 'API offline'
    : healthLoading
      ? 'Checking API…'
      : health
        ? `API ${health.status}`
        : 'API unknown';

  return (
    <header className="sticky top-0 z-20 border-b border-terminal-border bg-terminal-bg/95 backdrop-blur">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3 lg:px-6">
        <button
          type="button"
          onClick={onOpenMenu}
          className="rounded-lg border border-terminal-border p-2 text-terminal-muted hover:text-terminal-text lg:hidden"
          aria-label="Open navigation menu"
        >
          <Icon name="menu" size={16} />
        </button>

        <form onSubmit={submit} className="flex min-w-0 flex-1 items-center gap-2">
          <div className="relative min-w-0 flex-1 sm:max-w-xs">
            <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-terminal-muted">
              <Icon name="search" size={15} />
            </span>
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder="Symbol, e.g. RELIANCE or BTCUSDT"
              aria-label="Instrument symbol"
              className="h-9 w-full rounded-lg border border-terminal-border bg-terminal-panelAlt pl-8 pr-3 text-sm text-terminal-text placeholder:text-terminal-muted/70 focus:border-[#40598f] focus:outline-none focus:ring-1 focus:ring-[#40598f]"
            />
          </div>
          <select
            value={market}
            onChange={(event) => setMarket(event.target.value as Market)}
            aria-label="Market"
            className="h-9 rounded-lg border border-terminal-border bg-terminal-panelAlt px-2 text-xs text-terminal-text focus:border-[#40598f] focus:outline-none"
          >
            {marketOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <Button type="submit" size="sm" variant="primary" className="h-9">
            Load
          </Button>
        </form>

        <div className="flex items-center gap-2">
          <span
            className={cn(
              'flex items-center gap-1.5 rounded-full border border-terminal-border px-2.5 py-1 text-[11px]',
              statusTone(healthError, healthLoading),
            )}
            title={healthError ?? (health ? `Mode: ${health.mode}` : 'Waiting for the backend')}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
            {statusLabel}
          </span>
          <button
            type="button"
            onClick={refresh}
            className="rounded-lg border border-terminal-border p-2 text-terminal-muted transition-colors hover:text-terminal-text"
            aria-label="Refresh API status"
          >
            <Icon name="refresh" size={15} />
          </button>
        </div>
      </div>
    </header>
  );
}
