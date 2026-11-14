import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { Market } from '../../types/api';
import { cn } from '../../utils/format';
import { Button } from '../common/Button';

export interface InstrumentQuery {
  symbol: string;
  market: Market;
  exchange: string;
  interval: string;
  days: number;
  companyName: string;
}

export const marketOptions: Array<{ value: Market; label: string }> = [
  { value: 'india', label: 'India' },
  { value: 'global', label: 'Global' },
  { value: 'crypto', label: 'Crypto' },
];

const exchangeOptions: Record<Market, Array<{ value: string; label: string }>> = {
  india: [
    { value: 'NSE', label: 'NSE' },
    { value: 'BSE', label: 'BSE' },
  ],
  global: [
    { value: 'NASDAQ', label: 'NASDAQ' },
    { value: 'NYSE', label: 'NYSE' },
  ],
  crypto: [{ value: 'BINANCE', label: 'BINANCE' }],
};

const controlClasses =
  'h-7 rounded-sm border border-terminal-border bg-terminal-panelAlt px-2 text-xs text-terminal-text ' +
  'placeholder:text-terminal-muted/70 focus:border-terminal-accent focus:outline-none';

interface InstrumentFormProps {
  initial: InstrumentQuery;
  allowMarket?: boolean;
  allowCompanyName?: boolean;
  submitLabel?: string;
  busy?: boolean;
  onSubmit: (query: InstrumentQuery) => void;
  className?: string;
}

export function InstrumentForm({
  initial,
  allowMarket = true,
  allowCompanyName = true,
  submitLabel = 'Load',
  busy = false,
  onSubmit,
  className,
}: InstrumentFormProps) {
  const [symbol, setSymbol] = useState(initial.symbol);
  const [market, setMarket] = useState<Market>(initial.market);
  const [exchange, setExchange] = useState(initial.exchange);
  const [companyName, setCompanyName] = useState(initial.companyName);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSymbol(initial.symbol);
    setMarket(initial.market);
    setExchange(initial.exchange);
    setCompanyName(initial.companyName);
  }, [initial.symbol, initial.market, initial.exchange, initial.companyName]);

  function changeMarket(next: Market) {
    setMarket(next);
    setExchange(exchangeOptions[next][0].value);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanSymbol = symbol.trim().toUpperCase();
    if (!cleanSymbol) {
      setError('Enter a symbol');
      return;
    }
    setError(null);
    onSubmit({
      symbol: cleanSymbol,
      market,
      exchange: market === 'crypto' ? 'BINANCE' : exchange,
      interval: initial.interval,
      days: initial.days,
      companyName: companyName.trim(),
    });
  }

  return (
    <form onSubmit={submit} className={cn('flex flex-wrap items-center gap-1.5', className)}>
      <input
        value={symbol}
        onChange={(event) => setSymbol(event.target.value)}
        placeholder="Symbol"
        aria-label="Symbol"
        autoComplete="off"
        className={cn(controlClasses, 'w-28 uppercase')}
      />
      {allowCompanyName ? (
        <input
          value={companyName}
          onChange={(event) => setCompanyName(event.target.value)}
          placeholder="Company (Optional)"
          aria-label="Company Name"
          autoComplete="off"
          className={cn(controlClasses, 'w-40')}
        />
      ) : null}
      {allowMarket ? (
        <select
          value={market}
          onChange={(event) => changeMarket(event.target.value as Market)}
          aria-label="Market"
          className={controlClasses}
        >
          {marketOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : null}
      <select
        value={exchange}
        onChange={(event) => setExchange(event.target.value)}
        aria-label="Exchange"
        disabled={market === 'crypto'}
        className={cn(controlClasses, 'disabled:opacity-60')}
      >
        {exchangeOptions[market].map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <Button type="submit" size="sm" variant="primary" loading={busy}>
        {submitLabel}
      </Button>
      {error ? <span className="text-2xs text-terminal-red">{error}</span> : null}
    </form>
  );
}
