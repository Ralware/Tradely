import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useApiStatus } from '../contexts/ApiStatusContext';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import { analysisService } from '../services/analysisService';
import type { WatchlistItem } from '../types/api';
import { formatDateTime, formatNumber } from '../utils/format';
import { analysisPath } from '../utils/navigation';
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
  const signals = useApi((signal) => analysisService.getSignalsHistory(8, signal), []);
  const [removing, setRemoving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const watchlistItems = watchlist.data?.items ?? [];
  const positionCount = positions.data?.positions.length ?? 0;
  const buySignals = scanner.data?.items.filter((item) => item.strategy.state === 'BUY') ?? [];
  const realised = positions.data?.positions.reduce((sum, position) => sum + position.realised_pnl, 0) ?? 0;

  async function removeItem(item: WatchlistItem) {
    setActionError(null);
    setRemoving(`${item.market}:${item.symbol}:${item.exchange}`);
    try {
      await portfolioService.removeWatchlist({
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could not remove the instrument');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle="A single view of the backend status, the daily watchlist scan, open positions and recent signal audits. Nothing here is calculated in the browser."
        meta={
          health ? (
            <>
              <Badge tone="accent">{health.application}</Badge>
              <Badge>{health.mode}</Badge>
              <Badge tone={health.ai ? 'warning' : 'positive'}>{health.ai ? 'AI on' : 'AI off'}</Badge>
              <Badge tone={health.order_execution ? 'negative' : 'positive'}>
                {health.order_execution ? 'execution on' : 'no execution'}
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
              signals.reload();
            }}
          >
            Refresh all
          </Button>
        }
      />

      {healthError ? (
        <ErrorState
          className="mb-4"
          message={`${healthError}. Start the FastAPI backend on 127.0.0.1:8000 and reload.`}
          onRetry={refresh}
        />
      ) : null}

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Watchlist"
          value={watchlist.loading ? '…' : String(watchlistItems.length)}
          hint="Instruments in the daily scan"
        />
        <Stat
          label="Scanner BUY"
          value={scanner.loading ? '…' : String(buySignals.length)}
          tone={buySignals.length > 0 ? 'positive' : 'neutral'}
          hint={scanner.data ? `Scanned ${scanner.data.count} instruments` : 'Strategy state per instrument'}
        />
        <Stat
          label="Open positions"
          value={positions.loading ? '…' : String(positionCount)}
          hint="FIFO accounting"
        />
        <Stat
          label="Realised P&L"
          value={formatNumber(realised, 2)}
          tone={realised > 0 ? 'positive' : realised < 0 ? 'negative' : 'neutral'}
          hint="Across all currencies, unrealised value is not estimated"
        />
      </div>

      {actionError ? (
        <Notice tone="negative" className="mb-4">
          {actionError}
        </Notice>
      ) : null}

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-7"
          title="Daily watchlist scan"
          subtitle="The backend evaluates the configured daily strategy for every watchlist instrument."
          actions={
            <Link to="/markets">
              <Button size="sm" variant="ghost">
                Manage markets
              </Button>
            </Link>
          }
        >
          {scanner.loading && !scanner.data ? (
            <LoadingPanel label="Scanning watchlist…" rows={5} />
          ) : scanner.error ? (
            <ErrorState message={scanner.error} onRetry={scanner.reload} />
          ) : (
            <>
              <ScannerTable items={scanner.data?.items ?? []} />
              {scanner.data?.note ? (
                <p className="mt-3 text-[11px] text-terminal-muted">{scanner.data.note}</p>
              ) : null}
            </>
          )}
        </Card>

        <Card className="xl:col-span-5" title="Watchlist" subtitle="Add instruments from any analysis page.">
          {watchlist.loading && !watchlist.data ? (
            <LoadingPanel label="Loading watchlist…" rows={4} />
          ) : watchlist.error ? (
            <ErrorState message={watchlist.error} onRetry={watchlist.reload} />
          ) : (
            <WatchlistTable
              items={watchlistItems}
              removing={removing}
              onRemove={(item) => {
                void removeItem(item);
              }}
            />
          )}
        </Card>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card className="xl:col-span-7" title="Recent signal audits" subtitle="Newest backend signal evaluations.">
          {signals.loading && !signals.data ? (
            <LoadingPanel label="Loading signal history…" rows={4} />
          ) : signals.error ? (
            <ErrorState message={signals.error} onRetry={signals.reload} />
          ) : (signals.data?.signals.length ?? 0) === 0 ? (
            <EmptyState
              title="No signal history yet"
              description="Signal audits are recorded when an analysis page requests a symbol."
              icon="chart"
            />
          ) : (
            <ul className="divide-y divide-terminal-borderSoft">
              {(signals.data?.signals ?? []).map((signal, index) => (
                <li
                  key={`${signal.symbol}-${signal.as_of ?? 'na'}-${index}`}
                  className="flex flex-wrap items-center justify-between gap-2 py-2 first:pt-0 last:pb-0"
                >
                  <div className="min-w-0">
                    <Link
                      to={analysisPath(signal.symbol, signal.market)}
                      className="text-xs font-medium text-terminal-text hover:text-terminal-accent"
                    >
                      {signal.symbol}
                    </Link>
                    <p className="text-[10px] text-terminal-muted">
                      {signal.market} · {formatDateTime(signal.as_of)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <SignalBadge state={signal.state} />
                    <span className="num text-[11px] text-terminal-muted">
                      {signal.entry_reference === null
                        ? '—'
                        : `entry ${formatNumber(signal.entry_reference, 2)}`}
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="xl:col-span-5" title="Data providers" subtitle="Configuration state reported by the backend.">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking providers…" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <>
              <ProviderList providers={providers.providers} />
              <p className="mt-3 text-[10px] text-terminal-muted">
                Checked {formatDateTime(providers.checked_at)}
              </p>
            </>
          ) : null}
        </Card>
      </div>

      <Notice className="mt-4">
        Tradely is research-only. Signals are deterministic outputs of the backend strategy, not
        investment advice. Provider data can be delayed or incomplete; verify prices and corporate
        actions at the original source. Percentages shown here are values returned by the backend.
        {scanner.data?.items.some((item) => item.is_stale)
          ? ' At least one scanned instrument is marked stale.'
          : ''}
      </Notice>
    </div>
  );
}
