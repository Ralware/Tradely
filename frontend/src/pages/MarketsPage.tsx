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
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { ScannerTable } from '../components/tables/ScannerTable';
import { WatchlistTable } from '../components/tables/WatchlistTable';
import { CryptoMarketsTable } from '../components/tables/CryptoMarketsTable';
import { ProviderList } from '../components/tables/ProviderList';
import { useApiStatus } from '../contexts/ApiStatusContext';

const marketLabels: Record<Market, string> = {
  india: 'Indian equities',
  global: 'International equities',
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
  const crypto = useApi((signal) => marketService.getCryptoMarkets(undefined, signal), [], {
    enabled: tab === 'crypto',
  });

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
      setFormError('Enter a symbol.');
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
      setFormMessage(`${clean} added to the watchlist.`);
      setSymbol('');
      setDisplayName('');
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not add the instrument');
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
      watchlist.reload();
      scanner.reload();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could not remove the instrument');
    } finally {
      setRemoving(null);
    }
  }

  return (
    <div>
      <PageHeader
        title="Markets"
        subtitle="Watchlists, the daily scanner and provider state. Symbol entry is explicit — Tradely has no fabricated ticker database or instrument search endpoint."
        actions={
          <Button
            size="sm"
            icon="refresh"
            onClick={() => {
              watchlist.reload();
              scanner.reload();
              crypto.reload();
              refresh();
            }}
          >
            Refresh
          </Button>
        }
      />

      <Tabs
        className="mb-4"
        active={tab}
        onChange={changeTab}
        items={[
          { id: 'india', label: 'Indian equities', count: allItems.filter((i) => i.market === 'india').length },
          { id: 'global', label: 'International', count: allItems.filter((i) => i.market === 'global').length },
          { id: 'crypto', label: 'Crypto', count: allItems.filter((i) => i.market === 'crypto').length },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-5"
          title={`Add ${marketLabels[tab].toLowerCase()} instrument`}
          subtitle="Saved to the backend SQLite watchlist used by the scanner."
        >
          <form onSubmit={addInstrument} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2">
              <Input
                label="Symbol"
                value={symbol}
                onChange={(event) => setSymbol(event.target.value)}
                placeholder={tab === 'crypto' ? 'BTCUSDT' : tab === 'global' ? 'AAPL' : 'RELIANCE'}
                autoComplete="off"
              />
              {tab === 'crypto' ? (
                <Select
                  label="Exchange"
                  value={exchange}
                  onChange={(event) => setExchange(event.target.value)}
                  options={exchangeOptions.crypto}
                  disabled
                />
              ) : (
                <Select
                  label="Exchange"
                  value={exchange}
                  onChange={(event) => setExchange(event.target.value)}
                  options={exchangeOptions[tab]}
                />
              )}
            </div>
            <Input
              label="Display name (optional)"
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="Reliance Industries"
              autoComplete="off"
            />
            <Button type="submit" variant="primary" icon="plus" loading={saving}>
              Add to watchlist
            </Button>
          </form>

          {formMessage ? (
            <Notice tone="positive" className="mt-3">
              {formMessage}
            </Notice>
          ) : null}
          {formError ? (
            <Notice tone="negative" className="mt-3">
              {formError}
            </Notice>
          ) : null}
        </Card>

        <Card
          className="xl:col-span-7"
          title={`${marketLabels[tab]} watchlist`}
          subtitle="Open an instrument to run analysis, or remove it from the scanner."
        >
          {watchlist.loading && !watchlist.data ? (
            <LoadingPanel label="Loading watchlist…" rows={4} />
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

      <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-12">
        <Card
          className="xl:col-span-7"
          title="Daily scanner"
          subtitle="One backend strategy evaluation per watchlist instrument."
        >
          {scanner.loading && !scanner.data ? (
            <LoadingPanel label="Running scanner…" rows={5} />
          ) : scanner.error ? (
            <ErrorState message={scanner.error} onRetry={scanner.reload} />
          ) : (
            <>
              <ScannerTable items={filteredScanner} />
              {scanner.data?.note ? (
                <p className="mt-3 text-[11px] text-terminal-muted">{scanner.data.note}</p>
              ) : null}
            </>
          )}
        </Card>

        <Card className="xl:col-span-5" title="Provider configuration" subtitle="Reported by the backend, never assumed.">
          {providersLoading && !providers ? (
            <LoadingPanel label="Checking providers…" rows={4} />
          ) : providersError ? (
            <ErrorState message={providersError} onRetry={refresh} />
          ) : providers ? (
            <ProviderList providers={providers.providers} />
          ) : null}
        </Card>
      </div>

      {tab === 'crypto' ? (
        <Card
          className="mt-4"
          title="Crypto market metadata"
          subtitle="CoinGecko Demo aggregates. Price rows are provider values; analysis links use Binance Spot candles."
        >
          {crypto.loading && !crypto.data ? (
            <LoadingPanel label="Loading crypto markets…" rows={5} />
          ) : crypto.error ? (
            <ErrorState message={crypto.error} onRetry={crypto.reload} />
          ) : crypto.data ? (
            <>
              <CryptoMarketsTable markets={crypto.data.markets} />
              <p className="mt-3 text-[11px] text-terminal-muted">Source: {crypto.data.source}</p>
            </>
          ) : (
            <EmptyState title="No crypto metadata" icon="crypto" />
          )}
        </Card>
      ) : null}
    </div>
  );
}
