import { useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../../hooks/useApi';
import { analysisService } from '../../services/analysisService';
import { newsService } from '../../services/newsService';
import { portfolioService } from '../../services/portfolioService';
import type { Market } from '../../types/api';
import { cn, formatNumber, formatPercent, toneForNumber } from '../../utils/format';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { PageHeader } from '../common/PageHeader';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';
import { Stat } from '../common/Stat';
import { PriceChart } from '../charts/PriceChart';
import type { OverlayToggles } from '../charts/PriceChart';
import { IndicatorPanel } from '../charts/IndicatorPanel';
import { InstrumentForm } from './InstrumentForm';
import type { InstrumentQuery } from './InstrumentForm';
import { SignalCard } from '../signals/SignalCard';
import { RiskCalculator } from '../signals/RiskCalculator';
import { CandleTable } from '../tables/CandleTable';
import { IndicatorTable } from '../tables/IndicatorTable';
import { NewsList } from '../tables/NewsList';
import { EventsList } from '../tables/EventsList';
import { FundamentalsPanel } from './FundamentalsPanel';
import { SecFilingsPanel } from './SecFilingsPanel';

interface AnalysisWorkspaceProps {
  variant: 'stocks' | 'crypto';
  title: string;
  subtitle: string;
}

function ToggleChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        'rounded-md border px-2 py-1 text-[11px] font-medium transition-colors',
        active
          ? 'border-[#33477a] bg-[#141d33] text-terminal-accent'
          : 'border-terminal-border text-terminal-muted hover:text-terminal-text',
      )}
    >
      {children}
    </button>
  );
}

function asMarket(value: string | null, fallback: Market): Market {
  return value === 'india' || value === 'global' || value === 'crypto' ? value : fallback;
}

function asDays(value: string | null): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed >= 1 && parsed <= 3650 ? parsed : 500;
}

export function AnalysisWorkspace({ variant, title, subtitle }: AnalysisWorkspaceProps) {
  const [searchParams, setSearchParams] = useSearchParams();
  const defaultMarket: Market = variant === 'crypto' ? 'crypto' : 'india';
  const defaultExchange = variant === 'crypto' ? 'BINANCE' : 'NSE';
  const defaultSymbol = variant === 'crypto' ? 'BTCUSDT' : 'RELIANCE';

  const symbol = (searchParams.get('symbol') ?? '').trim().toUpperCase();
  const urlMarket = asMarket(searchParams.get('market'), defaultMarket);
  const market: Market =
    variant === 'crypto' ? 'crypto' : urlMarket === 'crypto' ? 'india' : urlMarket;
  const exchange = searchParams.get('exchange') ?? defaultExchange;
  const interval = searchParams.get('interval') ?? '1d';
  const days = asDays(searchParams.get('days'));
  const companyName = searchParams.get('company') ?? '';
  const enabled = symbol.length > 0;

  const [overlays, setOverlays] = useState<OverlayToggles>({
    sma: true,
    ema: false,
    bollinger: false,
  });
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(true);
  const [watchState, setWatchState] = useState<{
    loading: boolean;
    message: string | null;
    error: string | null;
  }>({ loading: false, message: null, error: null });

  const analysis = useApi(
    (signal) =>
      analysisService.getAnalysis({ symbol, market, exchange, interval, days }, signal),
    [symbol, market, exchange, interval, days],
    { enabled },
  );

  const indicatorSeries = useApi(
    (signal) =>
      analysisService.getIndicatorSeries(
        { symbol, market, exchange, interval, days, limit: 300 },
        signal,
      ),
    [symbol, market, exchange, interval, days],
    { enabled },
  );

  const news = useApi(
    (signal) =>
      newsService.getNews({ symbol, market, companyName: companyName || null }, signal),
    [symbol, market, companyName],
    { enabled },
  );

  const events = useApi(
    (signal) => newsService.getEvents({ symbol, market }, signal),
    [symbol, market],
    { enabled },
  );

  const currency = market === 'india' ? 'INR' : market === 'crypto' ? 'USDT' : 'USD';
  const intraday = interval !== '1d' && interval !== '1wk';

  const initialQuery: InstrumentQuery = {
    symbol: symbol || defaultSymbol,
    market,
    exchange,
    interval,
    days,
    companyName,
  };

  function handleSubmit(query: InstrumentQuery) {
    const next = new URLSearchParams();
    next.set('symbol', query.symbol);
    next.set('market', query.market);
    if (query.exchange) {
      next.set('exchange', query.exchange);
    }
    next.set('interval', query.interval);
    next.set('days', String(query.days));
    if (query.companyName) {
      next.set('company', query.companyName);
    }
    setWatchState({ loading: false, message: null, error: null });
    setSearchParams(next);
  }

  function refreshAll() {
    analysis.reload();
    indicatorSeries.reload();
    news.reload();
    events.reload();
  }

  async function addToWatchlist() {
    if (!symbol) {
      return;
    }
    setWatchState({ loading: true, message: null, error: null });
    try {
      await portfolioService.addWatchlist({ symbol, market, exchange });
      setWatchState({ loading: false, message: `${symbol} added to the watchlist.`, error: null });
    } catch (caught) {
      setWatchState({
        loading: false,
        message: null,
        error: caught instanceof Error ? caught.message : 'Could not add to watchlist',
      });
    }
  }

  const data = analysis.data;
  const previousClose =
    data && data.candles.length > 1 ? data.candles[data.candles.length - 2].close : null;
  const changePercent =
    data && previousClose ? ((data.latest.close - previousClose) / previousClose) * 100 : null;

  return (
    <div>
      <PageHeader
        title={title}
        subtitle={subtitle}
        meta={
          data ? (
            <>
              <Badge tone="accent">{data.source}</Badge>
              <Badge tone={data.is_adjusted ? 'positive' : 'warning'}>
                {data.is_adjusted ? 'adjusted' : 'unadjusted'}
              </Badge>
              {data.is_stale ? <Badge tone="warning">stale candle</Badge> : null}
              {data.history_truncated ? <Badge tone="warning">history truncated</Badge> : null}
            </>
          ) : null
        }
        actions={
          symbol ? (
            <>
              <Button size="sm" icon="refresh" onClick={refreshAll} loading={analysis.loading}>
                Refresh
              </Button>
              <Button
                size="sm"
                variant="primary"
                icon="plus"
                loading={watchState.loading}
                onClick={addToWatchlist}
              >
                Add to watchlist
              </Button>
            </>
          ) : null
        }
      />

      <Card className="mb-4" title="Instrument" subtitle="All analysis is produced by the FastAPI backend.">
        <InstrumentForm
          initial={initialQuery}
          allowMarket={variant !== 'crypto'}
          allowCompanyName={variant !== 'crypto'}
          busy={analysis.loading}
          onSubmit={handleSubmit}
        />
        {watchState.message ? (
          <Notice tone="positive" className="mt-3">
            {watchState.message}
          </Notice>
        ) : null}
        {watchState.error ? (
          <Notice tone="negative" className="mt-3">
            {watchState.error}
          </Notice>
        ) : null}
      </Card>

      {!symbol ? (
        <EmptyState
          title="Enter an instrument symbol"
          description="Use the form above or the global search in the top bar. No prices or signals are invented when a request has not been made."
          icon="search"
        />
      ) : analysis.loading && !data ? (
        <LoadingPanel label={`Loading ${symbol} analysis…`} rows={8} />
      ) : analysis.error ? (
        <ErrorState message={analysis.error} onRetry={analysis.reload} />
      ) : data ? (
        <div className="space-y-4">
          {data.warnings.length > 0 ? (
            <div className="space-y-2">
              {data.warnings.map((warning) => (
                <Notice key={warning} tone="warning">
                  {warning}
                </Notice>
              ))}
            </div>
          ) : null}

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Last close"
              value={`${formatNumber(data.latest.close, 2)} ${currency}`}
              hint={`As of ${data.as_of.slice(0, 10)}`}
            />
            <Stat
              label="Change vs prior bar"
              value={formatPercent(changePercent, 2, true)}
              tone={
                toneForNumber(changePercent) === 'positive'
                  ? 'positive'
                  : toneForNumber(changePercent) === 'negative'
                    ? 'negative'
                    : 'neutral'
              }
              hint="Derived from the two latest backend candles"
            />
            <Stat label="Volume" value={formatNumber(data.latest.volume, 0)} hint={data.interval} />
            <Stat
              label="History"
              value={`${data.candles.length} bars`}
              hint={data.history_pages ? `${data.history_pages} provider pages` : 'Provider dependent'}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card
              className="xl:col-span-8"
              title="Price chart"
              subtitle="Candles and volume from the backend. Indicator overlays use the latest backend-computed values."
              actions={
                <div className="flex flex-wrap gap-1.5">
                  <ToggleChip
                    active={overlays.sma}
                    onClick={() => setOverlays((previous) => ({ ...previous, sma: !previous.sma }))}
                  >
                    SMA
                  </ToggleChip>
                  <ToggleChip
                    active={overlays.ema}
                    onClick={() => setOverlays((previous) => ({ ...previous, ema: !previous.ema }))}
                  >
                    EMA
                  </ToggleChip>
                  <ToggleChip
                    active={overlays.bollinger}
                    onClick={() =>
                      setOverlays((previous) => ({ ...previous, bollinger: !previous.bollinger }))
                    }
                  >
                    Bollinger
                  </ToggleChip>
                  <ToggleChip active={showRsi} onClick={() => setShowRsi((value) => !value)}>
                    RSI pane
                  </ToggleChip>
                  <ToggleChip active={showMacd} onClick={() => setShowMacd((value) => !value)}>
                    MACD pane
                  </ToggleChip>
                </div>
              }
            >
              <PriceChart
                candles={data.candles}
                series={indicatorSeries.data?.series ?? null}
                latest={data.indicators}
                overlays={overlays}
                showRsi={showRsi}
                showMacd={showMacd}
                intraday={intraday}
                height={430}
              />
              {indicatorSeries.error ? (
                <Notice tone="warning" className="mt-2">
                  Indicator series unavailable ({indicatorSeries.error}). Price and volume still
                  render; RSI/MACD panes are hidden.
                </Notice>
              ) : null}
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-terminal-muted">
                <span>SMA 20 / 50 / 200 and EMA / Bollinger lines are latest backend values.</span>
                <span>Volume bars use backend OHLCV.</span>
              </div>
            </Card>

            <div className="xl:col-span-4">
              <SignalCard signal={data.strategy} currency={currency} />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <IndicatorPanel
              className="xl:col-span-6"
              indicators={data.indicators}
              close={data.latest.close}
            />
            <Card
              className="xl:col-span-6"
              title="Indicator table"
              subtitle="Every indicator returned by the backend for the latest completed bar."
            >
              <IndicatorTable indicators={data.indicators} />
            </Card>
          </div>

          <Card
            title="Recent candles"
            subtitle={`Last ${Math.min(30, data.candles.length)} bars · ${data.interval}`}
          >
            <CandleTable candles={data.candles} limit={30} />
          </Card>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card
              className="xl:col-span-6"
              title="Company / asset news"
              subtitle="Provider-returned items only. Open and verify each original publisher link."
            >
              {news.loading ? (
                <LoadingPanel label="Loading news…" rows={4} />
              ) : news.error ? (
                <ErrorState message={news.error} onRetry={news.reload} />
              ) : (
                <NewsList items={news.data?.items ?? []} note={news.data?.note} />
              )}
            </Card>

            <Card
              className="xl:col-span-6"
              title="Events & filings"
              subtitle="Structured provider records plus links to official exchange sources."
            >
              {events.loading ? (
                <LoadingPanel label="Loading events…" rows={3} />
              ) : events.error ? (
                <ErrorState message={events.error} onRetry={events.reload} />
              ) : (
                <EventsList
                  events={events.data?.events ?? []}
                  links={events.data?.official_source_links ?? []}
                  providerError={events.data?.provider_error ?? null}
                  note={events.data?.note}
                />
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <div className="xl:col-span-6">
              <RiskCalculator
                entry={data.strategy.entry_reference ?? data.latest.close}
                stop={data.strategy.stop_reference}
                currency={currency}
              />
            </div>

            {market === 'global' ? (
              <div className="xl:col-span-6">
                <SecFilingsPanel />
              </div>
            ) : market === 'crypto' ? (
              <Card className="xl:col-span-6" title="Crypto market context">
                <Notice>
                  Binance Spot candles and the backend strategy are shown above. CoinGecko aggregate
                  market metadata is available on the Markets page when a demo API key is configured.
                </Notice>
              </Card>
            ) : (
              <div className="xl:col-span-6">
                <FundamentalsPanel symbol={symbol} market={market} exchange={exchange} />
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}
