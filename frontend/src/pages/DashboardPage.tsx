import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useQuotes } from '../hooks/useQuotes';
import { useApiStatus } from '../contexts/ApiStatusContext';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import { analysisService } from '../services/analysisService';
import type { WatchlistItem } from '../types/api';
import { formatDateTime, formatNumber } from '../utils/format';
import { analysisPath } from '../utils/navigation';
import { quoteRefFromWatchlist } from '../utils/quotes';
import { notifyWatchlistChanged } from '../utils/events';
import { Badge } from '../components/common/Badge';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { PageHeader } from '../components/common/PageHeader';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { Stat } from '../components/common/Stat';
import { SignalBadge } from '../components/signals/SignalBadge';
import { ScannerTable } from '../components/tables/ScannerTable';
import { WatchlistTable } from '../components/tables/WatchlistTable';
import { ProviderList } from '../components/tables/ProviderList';

export function DashboardPage() {
  const { health, healthError, providers, providersLoading, providersError, refresh } = useApiStatus();
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const scanner = useApi((signal) => marketService.getScanner(signal), []);
  const positions = useApi((signal) => portfolioService.getPositions(signal), []);
  const summary = useApi((signal) => portfolioService.getSummary(signal), []);
  const signals = useApi((signal) => analysisService.getSignalsHistory(8, signal), []);
  const [removing, setRemoving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const watchlistItems = watchlist.data?.items ?? [];
  const watchlistRefs = watchlistItems.map(quoteRefFromWatchlist);
  const { quotes: watchlistQuotes, refresh: refreshWatchlistQuotes } = useQuotes(watchlistRefs);
  const positionCount = positions.data?.positions.length ?? 0;
  const buySignals = scanner.data?.items.filter((item) => item.strategy.state === 'BUY') ?? [];
  const realisedByCurrency = (summary.data?.currencies ?? [])
    .map((bucket) => `${bucket.currency} ${formatNumber(bucket.realized_pnl, 2)}`)
    .join(' · ');

  async function removeItem(item: WatchlistItem) {
    setActionError(null);
    setRemoving(`${item.market}:${item.symbol}:${item.exchange}`);
    try {
      await portfolioService.removeWatchlist({
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      notifyWatchlistChanged();
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could Not Remove Instrument');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="Backend Status · Watchlist Scan · Positions · Signals"
        meta={
          health ? (
            <>
              <Badge tone="accent">{health.application}</Badge>
              <Badge>{health.mode}</Badge>
              <Badge tone={health.order_execution ? 'negative' : 'positive'}>
                {health.order_execution ? 'Execution On' : 'No Order Execution'}
              </Badge>
            </>
          ) : null
        }
        actions={
          <Button
            size="sm"
            icon="refresh"
            onClick={() => {
              refresh();
              watchlist.reload();
              scanner.reload();
              positions.reload();
              summary.reload();
              signals.reload();
              refreshWatchlistQuotes();
            }}
          >
            Refresh All
          </Button>
        }
      />

      {healthError ? (
        <ErrorState
          className="mb-3"
          message={`${healthError}. Start FastAPI on 127.0.0.1:8000.`}
          onRetry={refresh}
        />
      ) : null}

      <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Watchlist"
          value={watchlist.loading ? '…' : String(watchlistItems.length)}
          hint="Scanned Instruments"
        />
        <Stat
          label="Scanner Buy"
          value={scanner.loading ? '…' : String(buySignals.length)}
          tone={buySignals.length > 0 ? 'positive' : 'neutral'}
          hint={scanner.data ? `${scanner.data.count} Scanned` : 'Daily Strategy'}
        />
        <Stat label="Open Positions" value={positions.loading ? '…' : String(positionCount)} hint="FIFO Accounting" />
        <Stat
          label="Realised P&L"
          value={summary.loading ? '…' : realisedByCurrency || '—'}
          tone="neutral"
          hint="Per Currency · Not Converted"
        />
      </div>

      {actionError ? (
        <Notice tone="negative" className="mb-3">
          {actionError}
        </Notice>
      ) : null}

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card
          className="xl:col-span-7"
          title="Watchlist Scan"
          actions={
            <Link to="/markets">
              <Button size="sm" variant="ghost">
                Manage Markets
              </Button>
            </Link>
          }
        >
          {scanner.loading && !scanner.data ? (
            <LoadingPanel label="Scanning Watchlist" rows={5} />
          ) : scanner.error ? (
            <ErrorState message={scanner.error} onRetry={scanner.reload} />
          ) : (
            <ScannerTable items={scanner.data?.items ?? []} />
          )}
        </Card>

        <Card className="xl:col-span-5" title="Watchlist">
          {watchlist.loading && !watchlist.data ? (
            <LoadingPanel label="Loading Watchlist" rows={4} />
          ) : watchlist.error ? (
            <ErrorState message={watchlist.error} onRetry={watchlist.reload} />
          ) : (
            <WatchlistTable
              items={watchlistItems}
              quotes={watchlistQuotes}
              removing={removing}
              onRemove={(item) => {
                void removeItem(item);
              }}
            />
          )}
        </Card>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-7" title="Recent Signals">
          {signals.loading && !signals.data ? (
            <LoadingPanel label="Loading Signals" rows={4} />
          ) : signals.error ? (
            <ErrorState message={signals.error} onRetry={signals.reload} />
          ) : (signals.data?.signals.length ?? 0) === 0 ? (
            <EmptyState title="No Signal History" icon="chart" />
          ) : (
            <ul className="divide-y divide-terminal-borderSoft">
              {(signals.data?.signals ?? []).map((signal, index) => (
                <li
                  key={`${signal.symbol}-${signal.as_of ?? 'na'}-${index}`}
                  className="flex flex-wrap items-center justify-between gap-2 py-1.5 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <Link
                      to={analysisPath(signal.symbol, signal.market)}
                      className="text-xs font-medium text-terminal-text hover:text-terminal-accent"
                    >
                      {signal.symbol}
                    </Link>
                    <p className="text-2xs text-terminal-muted">
                      {signal.market} · {formatDateTime(signal.as_of)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <SignalBadge state={signal.state} />
                    <span className="num text-2xs text-terminal-muted">
                      {signal.entry_reference === null
                        ? '—'
                        : `Entry ${formatNumber(signal.entry_reference, 2)}`}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-5" title="Data Providers">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking Providers" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <>
              <ProviderList providers={providers.providers} />
              <p className="mt-2 text-2xs text-terminal-muted">
                Checked {formatDateTime(providers.checked_at)}
              </p>
            </>
          ) : null}
        </Card>
      </div>
    </div>
  );
}
