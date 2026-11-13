import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import type { Market } from '../../types/api';
import { Button } from '../common/Button';
import { Input, Select } from '../common/Field';
import { cn } from '../../utils/format';

export interface InstrumentQuery {
  symbol: string;
  market: Market;
  exchange: string;
  interval: string;
  days: number;
  companyName: string;
}

export const marketOptions: Array<{ value: Market; label: string }> = [
  { value: 'india', label: 'Indian equities' },
  { value: 'global', label: 'International equities' },
  { value: 'crypto', label: 'Crypto spot' },
];

const exchangeOptions: Record<Market, Array<{ value: string; label: string }>> = {
  india: [
    { value: 'NSE', label: 'NSE' },
    { value: 'BSE', label: 'BSE' },
  ],
  global: [
    { value: 'NASDAQ', label: 'NASDAQ / US' },
    { value: 'NYSE', label: 'NYSE' },
  ],
  crypto: [{ value: 'BINANCE', label: 'Binance Spot' }],
};

const intervalOptions = [
  { value: '1d', label: '1 Day' },
  { value: '1h', label: '1 Hour' },
  { value: '15m', label: '15 Minutes' },
  { value: '1wk', label: '1 Week' },
];

const dayOptions = [120, 365, 500, 1000, 1825].map((days) => ({
  value: String(days),
  label: `${days} days`,
}));

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
  submitLabel = 'Load analysis',
  busy = false,
  onSubmit,
  className,
}: InstrumentFormProps) {
  const [symbol, setSymbol] = useState(initial.symbol);
  const [market, setMarket] = useState<Market>(initial.market);
  const [exchange, setExchange] = useState(initial.exchange);
  const [interval, setInterval] = useState(initial.interval);
  const [days, setDays] = useState(String(initial.days));
  const [companyName, setCompanyName] = useState(initial.companyName);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSymbol(initial.symbol);
    setMarket(initial.market);
    setExchange(initial.exchange);
    setInterval(initial.interval);
    setDays(String(initial.days));
    setCompanyName(initial.companyName);
  }, [
    initial.symbol,
    initial.market,
    initial.exchange,
    initial.interval,
    initial.days,
    initial.companyName,
  ]);

  function changeMarket(next: Market) {
    setMarket(next);
    setExchange(exchangeOptions[next][0].value);
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanSymbol = symbol.trim().toUpperCase();
    if (!cleanSymbol) {
      setError('Enter a symbol.');
      return;
    }
    setError(null);
    onSubmit({
      symbol: cleanSymbol,
      market,
      exchange,
      interval,
      days: Number(days),
      companyName: companyName.trim(),
    });
  }

  return (
    <form onSubmit={submit} className={cn('space-y-3', className)}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <Input
          label="Symbol"
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          placeholder="RELIANCE"
          autoComplete="off"
          wrapperClassName="sm:col-span-1 lg:col-span-2"
          error={error}
        />
        {allowCompanyName ? (
          <Input
            label="Company / asset name (optional)"
            value={companyName}
            onChange={(event) => setCompanyName(event.target.value)}
            placeholder="Reliance Industries"
            autoComplete="off"
            wrapperClassName="sm:col-span-1 lg:col-span-2"
          />
        ) : null}
        {allowMarket ? (
          <Select
            label="Market"
            value={market}
            onChange={(event) => changeMarket(event.target.value as Market)}
            options={marketOptions}
          />
        ) : null}
        <Select
          label="Exchange"
          value={exchange}
          onChange={(event) => setExchange(event.target.value)}
          options={exchangeOptions[market]}
          disabled={market === 'crypto'}
        />
        <Select
          label="Interval"
          value={interval}
          onChange={(event) => setInterval(event.target.value)}
          options={intervalOptions}
        />
        <Select
          label="History"
          value={days}
          onChange={(event) => setDays(event.target.value)}
          options={dayOptions}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" variant="primary" loading={busy}>
          {submitLabel}
        </Button>
        <p className="text-[11px] text-terminal-muted">
          The daily strategy is calibrated for completed daily candles only.
        </p>
      </div>
    </form>
  );
}
