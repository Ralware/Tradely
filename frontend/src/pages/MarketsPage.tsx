import { useState } from 'react';
import { useApi } from '../hooks/useApi';
import { useQuotes } from '../hooks/useQuotes';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import type { Instrument, WatchlistItem } from '../types/api';
import { Card } from '../components/common/Card';
import { PageHeader } from '../components/common/PageHeader';
import { Button } from '../components/common/Button';
import { ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { InstrumentSearch } from '../components/instruments/InstrumentSearch';
import { ScannerTable } from '../components/tables/ScannerTable';
import { WatchlistTable } from '../components/tables/WatchlistTable';
import { ProviderList } from '../components/tables/ProviderList';
import { useApiStatus } from '../contexts/ApiStatusContext';
import { notifyWatchlistChanged } from '../utils/events';
import { quoteRefFromWatchlist } from '../utils/quotes';

export function MarketsPage() {
  const [pending, setPending] = useState<Instrument | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const { providers, providersLoading, providersError, refresh } = useApiStatus();
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const scanner = useApi((signal) => marketService.getScanner(signal), []);

  const allItems = watchlist.data?.items ?? [];
  const watchlistRefs = allItems.map(quoteRefFromWatchlist);
  const { quotes: watchlistQuotes, refresh: refreshQuotes } = useQuotes(watchlistRefs);

  async function addInstrument() {
    if (!pending) {
      setFormError('Select an Instrument');
      return;
    }
    setFormError(null);
    setFormMessage(null);
    setSaving(true);
    try {
      await portfolioService.addWatchlist({ instrument_id: pending.instrument_id });
      setFormMessage(`${pending.symbol} Added to Watchlist`);
      setPending(null);
      notifyWatchlistChanged();
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could Not Add Instrument');
    } finally {
      setSaving(false);
    }
  }

  async function removeItem(item: WatchlistItem) {
    setFormError(null);
    setFormMessage(null);
    const key = item.instrument_id ?? `${item.market}:${item.symbol}:${item.exchange}`;
    setRemoving(key);
    try {
      await portfolioService.removeWatchlist({
        instrumentId: item.instrument_id,
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      notifyWatchlistChanged();
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could Not Remove Instrument');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Markets"
        subtitle="Watchlists · Scanner · Providers"
        actions={
          <Button
            size="sm"
            icon="refresh"
            onClick={() => {
              watchlist.reload();
              scanner.reload();
              refresh();
              refreshQuotes();
            }}
          >
            Refresh
          </Button>
        }
      />

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Add Instrument">
          <div className="space-y-2">
            <InstrumentSearch
              value={pending?.symbol ?? ''}
              placeholder="Search Ticker Or Name"
              onSelect={(instrument) => {
                setPending(instrument);
                setFormError(null);
                setFormMessage(null);
              }}
            />
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                icon="plus"
                loading={saving}
                disabled={!pending}
                onClick={addInstrument}
              >
                Add to Watchlist
              </Button>
              {pending ? (
                <span className="min-w-0 truncate text-2xs text-terminal-muted">
                  {pending.name} · {pending.exchange} · {pending.currency}
                </span>
              ) : null}
            </div>
          </div>

          {formMessage ? (
            <Notice tone="positive" className="mt-2">
              {formMessage}
            </Notice>
          ) : null}
          {formError ? (
            <Notice tone="negative" className="mt-2">
              {formError}
            </Notice>
          ) : null}
        </Card>

        <Card className="xl:col-span-7" title="Watchlist">
          {watchlist.loading && !watchlist.data ? (
            <LoadingPanel label="Loading Watchlist" rows={4} />
          ) : watchlist.error ? (
            <ErrorState message={watchlist.error} onRetry={watchlist.reload} />
          ) : (
            <WatchlistTable
              items={allItems}
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
        <Card className="xl:col-span-7" title="Daily Scanner">
          {scanner.loading && !scanner.data ? (
            <LoadingPanel label="Running Scanner" rows={5} />
          ) : scanner.error ? (
            <ErrorState message={scanner.error} onRetry={scanner.reload} />
          ) : (
            <ScannerTable items={scanner.data?.items ?? []} />
          )}
        </Card>

        <Card className="xl:col-span-5" title="Provider Configuration">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking Providers" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <ProviderList providers={providers.providers} />
          ) : null}
        </Card>
      </div>
    </div>
  );
}
