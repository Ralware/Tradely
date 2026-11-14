import { useState } from 'react';
import type { FormEvent } from 'react';
import { useApi } from '../hooks/useApi';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import type { Market, WatchlistItem } from '../types/api';
import { Card } from '../components/common/Card';
import { PageHeader } from '../components/common/PageHeader';
import { Button } from '../components/common/Button';
import { Input, Select } from '../components/common/Field';
import { Tabs } from '../components/common/Tabs';
import { ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { ScannerTable } from '../components/tables/ScannerTable';
import { WatchlistTable } from '../components/tables/WatchlistTable';
import { ProviderList } from '../components/tables/ProviderList';
import { useApiStatus } from '../contexts/ApiStatusContext';
import { notifyWatchlistChanged } from '../utils/events';

const marketLabels: Record<Market, string> = {
  india: 'Indian Equities',
  global: 'International Equities',
  crypto: 'Crypto',
};

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

export function MarketsPage() {
  const [tab, setTab] = useState<Market>('india');
  const [symbol, setSymbol] = useState('');
  const [exchange, setExchange] = useState('NSE');
  const [displayName, setDisplayName] = useState('');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [formMessage, setFormMessage] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const { providers, providersLoading, providersError, refresh } = useApiStatus();
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const scanner = useApi((signal) => marketService.getScanner(signal), []);

  const allItems = watchlist.data?.items ?? [];
  const filteredWatchlist = allItems.filter((item) => item.market === tab);
  const filteredScanner = (scanner.data?.items ?? []).filter((item) => item.market === tab);

  function changeTab(next: string) {
    const market = next as Market;
    setTab(market);
    setExchange(exchangeOptions[market][0].value);
    setFormError(null);
    setFormMessage(null);
  }

  async function addInstrument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    setFormMessage(null);
    const clean = symbol.trim().toUpperCase();
    if (!clean) {
      setFormError('Enter a Symbol');
      return;
    }
    setSaving(true);
    try {
      await portfolioService.addWatchlist({
        symbol: clean,
        market: tab,
        exchange: tab === 'crypto' ? 'BINANCE' : exchange,
        display_name: displayName.trim() || null,
      });
      setFormMessage(`${clean} Added to Watchlist`);
      setSymbol('');
      setDisplayName('');
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
            }}
          >
            Refresh
          </Button>
        }
      />

      <Tabs
        className="mb-3"
        active={tab}
        onChange={changeTab}
        items={[
          { id: 'india', label: 'Indian Equities', count: allItems.filter((i) => i.market === 'india').length },
          { id: 'global', label: 'International', count: allItems.filter((i) => i.market === 'global').length },
          { id: 'crypto', label: 'Crypto', count: allItems.filter((i) => i.market === 'crypto').length },
        ]}
      />

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
        <Card className="xl:col-span-5" title="Add Instrument">
          <form onSubmit={addInstrument} className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-2">
              <Input
                label="Symbol"
                value={symbol}
                onChange={(event) => setSymbol(event.target.value)}
                placeholder={tab === 'crypto' ? 'BTCUSDT' : tab === 'global' ? 'AAPL' : 'RELIANCE'}
                autoComplete="off"
              />
              <Select
                label="Exchange"
                value={exchange}
                onChange={(event) => setExchange(event.target.value)}
                options={exchangeOptions[tab]}
                disabled={tab === 'crypto'}
              />
            </div>
            <Input
              label="Display Name (Optional)"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Reliance Industries"
              autoComplete="off"
            />
            <Button type="submit" variant="primary" icon="plus" loading={saving}>
              Add to Watchlist
            </Button>
          </form>

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

        <Card className="xl:col-span-7" title={`${marketLabels[tab]} Watchlist`}>
          {watchlist.loading && !watchlist.data ? (
            <LoadingPanel label="Loading Watchlist" rows={4} />
          ) : watchlist.error ? (
            <ErrorState message={watchlist.error} onRetry={watchlist.reload} />
          ) : (
            <WatchlistTable
              items={filteredWatchlist}
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
            <ScannerTable items={filteredScanner} />
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
