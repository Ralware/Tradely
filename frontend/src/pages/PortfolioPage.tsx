import { useState } from 'react';
import type { FormEvent } from 'react';
import { useApi } from '../hooks/useApi';
import { portfolioService } from '../services/portfolioService';
import type { Market, Side } from '../types/api';
import { formatNumber } from '../utils/format';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { Input, Select, Textarea } from '../components/common/Field';
import { PageHeader } from '../components/common/PageHeader';
import { ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { Stat } from '../components/common/Stat';
import { PositionsTable } from '../components/tables/PositionsTable';
import { TransactionsTable } from '../components/tables/TransactionsTable';

const marketOptions = [
  { value: 'india', label: 'Indian Equities' },
  { value: 'global', label: 'International Equities' },
  { value: 'crypto', label: 'Crypto Spot' },
];

const sideOptions = [
  { value: 'BUY', label: 'BUY' },
  { value: 'SELL', label: 'SELL' },
];

const currencyFor: Record<Market, string> = {
  india: 'INR',
  global: 'USD',
  crypto: 'USDT',
};

function localDateTimeValue(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

export function PortfolioPage() {
  const transactions = useApi((signal) => portfolioService.getTransactions(signal), []);
  const positions = useApi((signal) => portfolioService.getPositions(signal), []);

  const [symbol, setSymbol] = useState('');
  const [market, setMarket] = useState<Market>('india');
  const [side, setSide] = useState<Side>('BUY');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const [tradeTime, setTradeTime] = useState(localDateTimeValue());
  const [fees, setFees] = useState('0');
  const [notes, setNotes] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  function changeMarket(next: Market) {
    setMarket(next);
    setMessage(null);
    setError(null);
  }

  async function recordTrade(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);

    const cleanSymbol = symbol.trim().toUpperCase();
    const parsedQuantity = Number(quantity);
    const parsedPrice = Number(price);
    const parsedFees = Number(fees || '0');
    const parsedTime = new Date(tradeTime);

    if (!cleanSymbol) {
      setError('Enter a Symbol');
      return;
    }
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setError('Quantity Must Be Positive');
      return;
    }
    if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) {
      setError('Price Must Be Positive');
      return;
    }
    if (Number.isNaN(parsedTime.getTime())) {
      setError('Enter a Valid Trade Time');
      return;
    }
    if (!Number.isFinite(parsedFees) || parsedFees < 0) {
      setError('Fees Must Be Zero or Positive');
      return;
    }

    setSaving(true);
    try {
      await portfolioService.addTransaction({
        symbol: cleanSymbol,
        market,
        side,
        quantity: parsedQuantity,
        price: parsedPrice,
        trade_time: parsedTime.toISOString(),
        currency: currencyFor[market],
        fees: parsedFees,
        notes: notes.trim() || null,
      });
      setMessage(`${side} ${cleanSymbol} Recorded`);
      setSymbol('');
      setQuantity('');
      setPrice('');
      setFees('0');
      setNotes('');
      transactions.reload();
      positions.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could Not Record Transaction');
    } finally {
      setSaving(false);
    }
  }

  const positionRows = positions.data?.positions ?? [];
  const transactionRows = transactions.data?.transactions ?? [];
  const totalRealised = positionRows.reduce((sum, position) => sum + position.realised_pnl, 0);

  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle="FIFO Ledger · Positions · Transactions"
        actions={
          <Button
            size="sm"
            icon="refresh"
            onClick={() => {
              transactions.reload();
              positions.reload();
            }}
          >
            Refresh
          </Button>
        }
      />

      <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Open Positions" value={String(positionRows.length)} hint="All Markets" />
        <Stat label="Transactions" value={String(transactionRows.length)} hint="Ledger Rows" />
        <Stat
          label="Realised P&L"
          value={formatNumber(totalRealised, 2)}
          tone={totalRealised > 0 ? 'positive' : totalRealised < 0 ? 'negative' : 'neutral'}
          hint="Not Currency Converted"
        />
        <Stat
          label="Accounting"
          value={positions.data?.accounting_method ?? 'FIFO'}
          hint="Backend Method"
        />
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Record Transaction">
          <form onSubmit={recordTrade} className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                label="Symbol"
                value={symbol}
                onChange={(event) => setSymbol(event.target.value)}
                placeholder="RELIANCE"
                autoComplete="off"
              />
              <Select
                label="Market"
                value={market}
                onChange={(event) => changeMarket(event.target.value as Market)}
                options={marketOptions}
              />
              <Select
                label="Side"
                value={side}
                onChange={(event) => setSide(event.target.value as Side)}
                options={sideOptions}
              />
              <Input label="Currency" value={currencyFor[market]} readOnly hint="From Market" />
              <Input
                label="Quantity"
                type="number"
                min={0}
                step="any"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
              <Input
                label="Price per Unit"
                type="number"
                min={0}
                step="any"
                value={price}
                onChange={(event) => setPrice(event.target.value)}
              />
              <Input
                label="Trade Time"
                type="datetime-local"
                value={tradeTime}
                onChange={(event) => setTradeTime(event.target.value)}
              />
              <Input
                label="Fees"
                type="number"
                min={0}
                step="any"
                value={fees}
                onChange={(event) => setFees(event.target.value)}
              />
            </div>
            <Textarea
              label="Notes (Optional)"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Broker reference, charges, partial fill"
            />
            <Button type="submit" variant="primary" icon="plus" loading={saving}>
              Record Transaction
            </Button>
          </form>

          {message ? (
            <Notice tone="positive" className="mt-2">
              {message}
            </Notice>
          ) : null}
          {error ? (
            <Notice tone="negative" className="mt-2">
              {error}
            </Notice>
          ) : null}
        </Card>

        <Card className="xl:col-span-7" title="Open Positions">
          {positions.loading && !positions.data ? (
            <LoadingPanel label="Loading Positions" rows={4} />
          ) : positions.error ? (
            <ErrorState message={positions.error} onRetry={positions.reload} />
          ) : (
            <PositionsTable positions={positionRows} />
          )}
        </Card>
      </div>

      <Card className="mt-3" title="Transaction Ledger">
        {transactions.loading && !transactions.data ? (
          <LoadingPanel label="Loading Transactions" rows={5} />
        ) : transactions.error ? (
          <ErrorState message={transactions.error} onRetry={transactions.reload} />
        ) : (
          <TransactionsTable transactions={transactionRows} />
        )}
      </Card>
    </div>
  );
}
