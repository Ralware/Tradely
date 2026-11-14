import { useState } from 'react';
import type { FormEvent } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useApiStatus } from '../../contexts/ApiStatusContext';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import type { Market } from '../../types/api';
import { changeDigits, cn, formatNumber, formatPercent, formatSignedFixed, toneForNumber } from '../../utils/format';
import { Icon } from '../common/Icon';

const navigation = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/markets', label: 'Markets' },
  { to: '/stocks', label: 'Stocks' },
  { to: '/crypto', label: 'Crypto' },
  { to: '/portfolio', label: 'Portfolio' },
  { to: '/backtesting', label: 'Backtesting' },
  { to: '/settings', label: 'Settings' },
];

const marketOptions: Array<{ value: Market; label: string }> = [
  { value: 'india', label: 'India' },
  { value: 'global', label: 'Global' },
  { value: 'crypto', label: 'Crypto' },
];

function priceDigits(value: number | null): number {
  if (value === null) return 2;
  if (value >= 1000) return 2;
  if (value >= 1) return 4;
  return 6;
}

function toneClass(value: number | null): string {
  const tone = toneForNumber(value);
  if (tone === 'positive') return 'text-terminal-green';
  if (tone === 'negative') return 'text-terminal-red';
  return 'text-terminal-muted';
}

export function TopBar({
  onOpenMenu,
  onOpenWatchlist,
}: {
  onOpenMenu: () => void;
  onOpenWatchlist: () => void;
}) {
  const navigate = useNavigate();
  const { health, healthLoading, healthError, refresh } = useApiStatus();
  const selected = useSelectedInstrument();
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

  const quote = selected.quote;
  const statusLabel = healthError
    ? 'Offline'
    : healthLoading
      ? 'Checking'
      : health
        ? 'Online'
        : 'Unknown';
  const statusTone = healthError
    ? 'text-terminal-red'
    : healthLoading
      ? 'text-terminal-amber'
      : 'text-terminal-green';

  return (
    <header className="z-30 flex h-11 shrink-0 items-center gap-2 border-b border-terminal-border bg-terminal-panel px-2 sm:px-3">
      <button
        type="button"
        onClick={onOpenMenu}
        className="rounded p-1.5 text-terminal-muted hover:bg-white/[0.05] hover:text-terminal-text xl:hidden"
        aria-label="Open Navigation"
      >
        <Icon name="menu" size={15} />
      </button>

      <Link to="/" className="flex shrink-0 items-center gap-1.5">
        <span className="flex h-6 w-6 items-center justify-center rounded-sm bg-terminal-accent text-white">
          <Icon name="chart" size={14} />
        </span>
        <span className="text-[13px] font-semibold tracking-tight text-terminal-text">Tradely</span>
      </Link>

      <nav className="ml-1 hidden items-center gap-0.5 xl:flex" aria-label="Main Navigation">
        {navigation.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'rounded px-2 py-1 text-[11px] font-medium transition-colors',
                isActive
                  ? 'bg-[#20242b] text-terminal-text'
                  : 'text-terminal-muted hover:bg-white/[0.04] hover:text-terminal-text',
              )
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>

      <div className="ml-auto flex min-w-0 items-center gap-2">
        <div className="hidden items-center gap-2 border-r border-terminal-border pr-3 lg:flex">
          {selected.enabled ? (
            <>
              <span className="text-xs font-semibold text-terminal-text">{selected.symbol}</span>
              <span className="num text-xs text-terminal-text">
                {quote ? formatNumber(quote.last, priceDigits(quote.last)) : '—'}
              </span>
              <span className={cn('num text-2xs', toneClass(quote?.change ?? null))}>
                {quote?.change === null || quote?.change === undefined
                  ? '—'
                  : formatSignedFixed(quote.change, changeDigits(quote.change))}
              </span>
              <span className={cn('num text-2xs', toneClass(quote?.changePct ?? null))}>
                {formatPercent(quote?.changePct ?? null, 2, true)}
              </span>
            </>
          ) : (
            <span className="text-2xs text-terminal-muted">No Instrument Selected</span>
          )}
        </div>

        <form onSubmit={submit} className="flex min-w-0 items-center gap-1">
          <div className="relative min-w-0 flex-1 sm:w-52">
            <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-terminal-muted">
              <Icon name="search" size={13} />
            </span>
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder="Search Symbol"
              aria-label="Instrument Symbol"
              autoComplete="off"
              className="h-7 w-full rounded-sm border border-terminal-border bg-terminal-panelAlt pl-7 pr-2 text-xs text-terminal-text placeholder:text-terminal-muted/70 focus:border-terminal-accent focus:outline-none"
            />
          </div>
          <select
            value={market}
            onChange={(event) => setMarket(event.target.value as Market)}
            aria-label="Search Market"
            className="hidden h-7 rounded-sm border border-terminal-border bg-terminal-panelAlt px-1 text-2xs text-terminal-text focus:border-terminal-accent focus:outline-none sm:block"
          >
            {marketOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <button
            type="submit"
            aria-label="Load Instrument"
            title="Load Instrument"
            className="flex h-7 w-7 items-center justify-center rounded-sm border border-terminal-border text-terminal-muted hover:border-terminal-accent hover:text-terminal-text"
          >
            <Icon name="arrowUp" size={13} />
          </button>
        </form>

        <button
          type="button"
          onClick={refresh}
          title={healthError ?? (health ? `${health.application} · ${health.mode}` : 'Backend Status')}
          aria-label="Refresh Backend Status"
          className="flex items-center gap-1.5 rounded-sm px-1.5 py-1 hover:bg-white/[0.05]"
        >
          <span className={cn('h-1.5 w-1.5 rounded-full bg-current', statusTone)} aria-hidden="true" />
          <span className={cn('hidden text-2xs 2xl:inline', statusTone)}>{statusLabel}</span>
        </button>

        <button
          type="button"
          onClick={onOpenWatchlist}
          className="rounded p-1.5 text-terminal-muted hover:bg-white/[0.05] hover:text-terminal-text xl:hidden"
          aria-label="Open Watchlist"
          title="Open Watchlist"
        >
          <Icon name="portfolio" size={15} />
        </button>
      </div>
    </header>
  );
}
