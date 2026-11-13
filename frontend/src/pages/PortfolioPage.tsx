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
  { value: 'india', label: 'Indian equities' },
  { value: 'global', label: 'International equities' },
  { value: 'crypto', label: 'Crypto spot' },
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
      setError('Enter a symbol.');
      return;
    }
    if (!Number.isFinite(parsedQuantity) || parsedQuantity <= 0) {
      setError('Quantity must be a positive number.');
      return;
    }
    if (!Number.isFinite(parsedPrice) || parsedPrice <= 0) {
      setError('Price must be a positive number.');
      return;
    }
    if (Number.isNaN(parsedTime.getTime())) {
      setError('Enter a valid trade time.');
      return;
    }
    if (!Number.isFinite(parsedFees) || parsedFees < 0) {
      setError('Fees must be zero or positive.');
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
      setMessage(`${side} ${cleanSymbol} recorded. FIFO positions were recalculated by the backend.`);
      setSymbol('');
      setQuantity('');
      setPrice('');
      setFees('0');
      setNotes('');
      transactions.reload();
      positions.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not record the transaction');
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
        subtitle="A ledger of actual trades only. Cost basis and realised P&L use the backend FIFO accounting method. Tradely does not simulate or execute orders."
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

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Open positions" value={String(positionRows.length)} hint="Across all markets" />
        <Stat label="Transactions" value={String(transactionRows.length)} hint="Recorded ledger rows" />
        <Stat
          label="Realised P&L"
          value={formatNumber(totalRealised, 2)}
          tone={totalRealised > 0 ? 'positive' : totalRealised < 0 ? 'negative' : 'neutral'}
          hint="Sum across currencies; not converted"
        />
        <Stat
          label="Accounting"
          value={positions.data?.accounting_method ?? 'FIFO'}
          hint="Method reported by the backend"
        />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-5"
          title="Record a transaction"
          subtitle="Real trades only. The backend stores the row and recomputes FIFO positions."
        >
          <form onSubmit={recordTrade} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
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
              <Input
                label={`Currency`}
                value={currencyFor[market]}
                readOnly
                hint="Derived from the market, stored with the trade."
              />
              <Input
                label="Quantity"
                type="number"
                min={0}
                step="any"
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
              />
              <Input
                label="Price per unit"
                type="number"
                min={0}
                step="any"
                value={price}
                onChange={(event) => setPrice(event.target.value)}
              />
              <Input
                label="Trade time"
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
              label="Notes (optional)"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Broker reference, charges, partial-fill note…"
            />
            <Button type="submit" variant="primary" icon="plus" loading={saving}>
              Record transaction
            </Button>
          </form>

          {message ? (
            <Notice tone="positive" className="mt-3">
              {message}
            </Notice>
          ) : null}
          {error ? (
            <Notice tone="negative" className="mt-3">
              {error}
            </Notice>
          ) : null}
        </Card>

        <Card
          className="xl:col-span-7"
          title="Open positions"
          subtitle="FIFO cost basis and realised P&L exactly as returned by the backend."
        >
          {positions.loading && !positions.data ? (
            <LoadingPanel label="Loading positions…" rows={4} />
          ) : positions.error ? (
            <ErrorState message={positions.error} onRetry={positions.reload} />
          ) : (
            <>
              <PositionsTable positions={positionRows} />
              {positions.data?.note ? (
                <p className="mt-3 text-[11px] text-terminal-muted">{positions.data.note}</p>
              ) : null}
            </>
          )}
        </Card>
      </div>

      <Card
        className="mt-4"
        title="Transaction ledger"
        subtitle={
          transactions.data?.mode
            ? `Backend mode: ${transactions.data.mode}. Newest rows appear first.`
            : 'Newest rows appear first.'
        }
      >
        {transactions.loading && !transactions.data ? (
          <LoadingPanel label="Loading transactions…" rows={5} />
        ) : transactions.error ? (
          <ErrorState message={transactions.error} onRetry={transactions.reload} />
        ) : (
          <TransactionsTable transactions={transactionRows} />
        )}
      </Card>

      <Notice className="mt-4">
        Positions are derived from recorded transactions using FIFO. The ledger does not estimate
        live market value, unrealised P&L or currency conversion. Verify every fill against your
        broker contract note.
      </Notice>
    </div>
  );
}
