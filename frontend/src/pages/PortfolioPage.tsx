import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { useQuotes } from "../hooks/useQuotes";
import { portfolioService } from "../services/portfolioService";
import type {
  AddTransactionResponse,
  Position,
  Transaction,
} from "../types/api";
import { Button } from "../components/common/Button";
import { Card } from "../components/common/Card";
import { PageHeader } from "../components/common/PageHeader";
import { ErrorState, LoadingPanel, Notice } from "../components/common/States";
import { PositionsTable } from "../components/tables/PositionsTable";
import { TransactionsTable } from "../components/tables/TransactionsTable";
import { PortfolioSummaryCards } from "../components/portfolio/PortfolioSummaryCards";
import { PositionDetailPanel } from "../components/portfolio/PositionDetailPanel";
import { TransactionForm } from "../components/portfolio/TransactionForm";

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "Request failed";
}

function intentLabel(transaction: Transaction): string {
  switch (transaction.intent ?? transaction.side) {
    case "BUY":
      return "Buy";
    case "SELL":
      return "Sell";
    case "SELL_SHORT":
      return "Sell Short";
    case "BUY_TO_COVER":
      return "Buy To Cover";
  }
}

export function PortfolioPage() {
  const positions = useApi(
    (signal) => portfolioService.getPositions(signal),
    [],
    { keepPreviousData: true },
  );
  const summary = useApi((signal) => portfolioService.getSummary(signal), [], {
    keepPreviousData: true,
  });
  const transactions = useApi(
    (signal) => portfolioService.getTransactions(signal),
    [],
    { keepPreviousData: true },
  );

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
    (signal) => portfolioService.getPositionDetail(selectedId ?? "", signal),
    [selectedId],
    {
      enabled: Boolean(selectedId),
      keepPreviousData: true,
      keepPreviousDataKey: selectedId,
    },
  );

  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [closeRequest, setCloseRequest] = useState<{ position: Position; requestId: number } | null>(null);
  const closeRequestId = useRef(0);

  // Refresh backend valuations when live crypto ticks arrive, at a throttled
  // rate. React never recalculates FIFO or P&L itself.
  const lastValuationRefresh = useRef(0);
  const quoteSignature = [...quotes.values()]
    .map(
      (quote) => `${quote.instrument_id}:${quote.price}:${quote.retrieved_at}`,
    )
    .join("|");
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
    if (
      !selectedId ||
      !positionRows.some((row) => row.instrument_id === selectedId)
    ) {
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
    reloadPortfolio();
  }

  async function deleteTransaction(transaction: Transaction) {
    const sideLabel = intentLabel(transaction);
    if (
      !window.confirm(
        `Delete the ${sideLabel} of ${transaction.symbol} recorded ${transaction.trade_time}? The ledger will be revalidated.`,
      )
    ) {
      return;
    }
    setDeleting(transaction.id);
    setError(null);
    setMessage(null);
    try {
      await portfolioService.deleteTransaction(transaction.id);
      setMessage(
        `${sideLabel} ${transaction.symbol} deleted; remaining ledger revalidated`,
      );
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

  function startClosePosition(position: Position) {
    setSelectedId(position.instrument_id);
    closeRequestId.current += 1;
    setCloseRequest({ position, requestId: closeRequestId.current });
  }

  return (
    <div className="w-full px-4 py-4 lg:px-6">
      <PageHeader
        title="Portfolio"
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
        actions={
          <span className="text-2xs text-terminal-muted">
            {positionRows.length} Open ·{" "}
            {transactions.data?.transactions.length ?? 0} Ledger Rows
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
        actions={
          <span className="text-2xs text-terminal-muted">
            {positions.data ? `${positionRows.length} Positions` : "Loading"}
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

      <Card className="mb-3" title="Position Details">
        <PositionDetailPanel
          detail={detail.data}
          loading={detail.loading}
          error={detail.error}
          onReload={detail.reload}
          onClose={() => setSelectedId(null)}
          onClosePosition={startClosePosition}
        />
      </Card>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <TransactionForm positions={positionRows} onRecorded={handleRecorded} closeRequest={closeRequest} />

        <Card
          className="xl:col-span-8"
          title="Transaction Ledger"
          actions={
            <span className="text-2xs text-terminal-muted">
              {transactions.data
                ? `${transactions.data.transactions.length} Rows`
                : "Loading"}
            </span>
          }
        >
          {transactions.loading && !transactions.data ? (
            <LoadingPanel label="Loading Transactions" rows={5} />
          ) : transactions.error ? (
            <ErrorState
              message={transactions.error}
              onRetry={transactions.reload}
            />
          ) : (
            <TransactionsTable
              transactions={transactions.data?.transactions ?? []}
              onDelete={(transaction) => {
                void deleteTransaction(transaction);
              }}
              deleting={deleting}
            />
          )}
        </Card>
      </div>
    </div>
  );
}
