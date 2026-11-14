import { useEffect, useMemo, useRef, useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useQuotes } from '../hooks/useQuotes';
import { portfolioService } from '../services/portfolioService';
import type { AddTransactionResponse, Position, Transaction } from '../types/api';
import { notifyWatchlistChanged } from '../utils/events';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { PageHeader } from '../components/common/PageHeader';
import { ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { PositionsTable } from '../components/tables/PositionsTable';
import { TransactionsTable } from '../components/tables/TransactionsTable';
import { PortfolioSummaryCards } from '../components/portfolio/PortfolioSummaryCards';
import { PositionDetailPanel } from '../components/portfolio/PositionDetailPanel';
import { TransactionForm } from '../components/portfolio/TransactionForm';

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed';
}

export function PortfolioPage() {
  const positions = useApi((signal) => portfolioService.getPositions(signal), []);
  const summary = useApi((signal) => portfolioService.getSummary(signal), []);
  const transactions = useApi((signal) => portfolioService.getTransactions(signal), []);

  const positionRows = positions.data?.positions ?? [];
  const positionRefs = useMemo(
    () =>
      positionRows.map((position) => ({
        instrument_id: position.instrument_id,
        symbol: position.symbol,
        market: position.market,
        exchange: position.exchange,
        currency: position.currency,
      })),
    [positionRows],
  );
  const { quotes, refresh: refreshQuotes } = useQuotes(positionRefs);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const detail = useApi(
    (signal) => portfolioService.getPositionDetail(selectedId ?? '', signal),
    [selectedId],
    { enabled: Boolean(selectedId) },
  );

  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Refresh backend valuations when live crypto ticks arrive, at a throttled
  // rate. React never recalculates FIFO or P&L itself.
  const lastValuationRefresh = useRef(0);
  const quoteSignature = [...quotes.values()]
    .map((quote) => `${quote.instrument_id}:${quote.price}:${quote.retrieved_at}`)
    .join('|');
  useEffect(() => {
    if (!quoteSignature) {
      return;
    }
    const now = Date.now();
    if (now - lastValuationRefresh.current < 8000) {
      return;
    }
    lastValuationRefresh.current = now;
    positions.reload();
    summary.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quoteSignature]);

  useEffect(() => {
    if (positionRows.length === 0) {
      if (selectedId !== null) {
        setSelectedId(null);
      }
      return;
    }
    if (!selectedId || !positionRows.some((row) => row.instrument_id === selectedId)) {
      setSelectedId(positionRows[0].instrument_id);
    }
  }, [positionRows, selectedId]);

  function reloadPortfolio() {
    positions.reload();
    summary.reload();
    transactions.reload();
    detail.reload();
    refreshQuotes();
  }

  function handleRecorded(saved: AddTransactionResponse, savedMessage: string) {
    setError(null);
    setMessage(savedMessage);
    const position = saved.position;
    if (position) {
      setSelectedId(position.instrument_id);
    }
    notifyWatchlistChanged();
    reloadPortfolio();
  }

  async function deleteTransaction(transaction: Transaction) {
    if (
      !window.confirm(
        `Delete the ${transaction.side} of ${transaction.symbol} recorded ${transaction.trade_time}? The ledger will be revalidated.`,
      )
    ) {
      return;
    }
    setDeleting(transaction.id);
    setError(null);
    setMessage(null);
    try {
      await portfolioService.deleteTransaction(transaction.id);
      setMessage(`${transaction.side} ${transaction.symbol} deleted; remaining ledger revalidated`);
      notifyWatchlistChanged();
      reloadPortfolio();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setDeleting(null);
    }
  }

  function selectPosition(position: Position) {
    setSelectedId(position.instrument_id);
  }

  return (
    <div>
      <PageHeader
        title="Portfolio"
        subtitle="Amount-Based Entry · Live Valuation · FIFO Accounting"
        actions={
          <Button size="sm" icon="refresh" onClick={reloadPortfolio}>
            Refresh
          </Button>
        }
      />

      {message ? (
        <Notice tone="positive" className="mb-2">
          {message}
        </Notice>
      ) : null}
      {error ? (
        <Notice tone="negative" className="mb-2">
          {error}
        </Notice>
      ) : null}

      <Card
        className="mb-3"
        title="Portfolio Summary"
        subtitle="Backend FIFO Values · No Cross-Currency Totals"
        actions={
          <span className="text-2xs text-terminal-muted">
            {positionRows.length} Open · {transactions.data?.transactions.length ?? 0} Ledger Rows
          </span>
        }
      >
        <PortfolioSummaryCards
          summary={summary.data}
          loading={summary.loading}
          error={summary.error}
        />
      </Card>

      <Card
        className="mb-3"
        title="Open Positions"
        subtitle="Invested Value, Market Value and P&L Calculated by the Backend"
        actions={
          <span className="text-2xs text-terminal-muted">
            {positions.data ? `${positionRows.length} Positions` : 'Loading'}
          </span>
        }
      >
        {positions.loading && !positions.data ? (
          <LoadingPanel label="Loading Positions" rows={4} />
        ) : positions.error ? (
          <ErrorState message={positions.error} onRetry={positions.reload} />
        ) : (
          <PositionsTable
            positions={positionRows}
            selectedId={selectedId}
            onSelect={selectPosition}
          />
        )}
      </Card>

      <Card
        className="mb-3"
        title="Position Details"
        subtitle="FIFO Lots · Trade History · Actual Candles"
      >
        <PositionDetailPanel
          detail={detail.data}
          loading={detail.loading}
          error={detail.error}
          onReload={detail.reload}
          onClose={() => setSelectedId(null)}
        />
      </Card>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <TransactionForm positions={positionRows} onRecorded={handleRecorded} />

        <Card
          className="xl:col-span-8"
          title="Transaction Ledger"
          subtitle="Immutable Trade History · Deletion Revalidates FIFO"
          actions={
            <span className="text-2xs text-terminal-muted">
              {transactions.data ? `${transactions.data.transactions.length} Rows` : 'Loading'}
            </span>
          }
        >
          {transactions.loading && !transactions.data ? (
            <LoadingPanel label="Loading Transactions" rows={5} />
          ) : transactions.error ? (
            <ErrorState message={transactions.error} onRetry={transactions.reload} />
          ) : (
            <TransactionsTable
              transactions={transactions.data?.transactions ?? []}
              onDelete={(transaction) => {
                void deleteTransaction(transaction);
              }}
              deleting={deleting}
            />
          )}
          <p className="mt-2 text-2xs leading-relaxed text-terminal-muted">
            Realized P&amp;L uses FIFO: buy fees are added to lot cost basis and sell fees reduce
            proceeds. Fully sold instruments disappear from Open Positions but remain in this ledger.
            Transaction amounts are the gross asset notional entered at recording time; quantities
            and reference prices are stored per row for accounting.
          </p>
        </Card>
      </div>
    </div>
  );
}
