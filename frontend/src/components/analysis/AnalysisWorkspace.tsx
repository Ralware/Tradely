import { useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useApi } from '../../hooks/useApi';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { analysisService } from '../../services/analysisService';
import { newsService } from '../../services/newsService';
import { portfolioService } from '../../services/portfolioService';
import type { Instrument } from '../../types/api';
import { changeDigits, cn, formatDate, formatNumber, formatPercent, formatSignedFixed, toneForNumber } from '../../utils/format';
import { defaultDaysFor, intervalLabel, isIntradayInterval } from '../../utils/timeframes';
import { notifyWatchlistChanged } from '../../utils/events';
import { instrumentPath } from '../../utils/navigation';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';
import { KeyValue } from '../common/Stat';
import { Tabs } from '../common/Tabs';
import { PriceChart } from '../charts/PriceChart';
import type { OverlayToggles } from '../charts/PriceChart';
import { IndicatorPanel } from '../charts/IndicatorPanel';
import { InstrumentSearch } from '../instruments/InstrumentSearch';
import { SignalCard } from '../signals/SignalCard';
import { RiskCalculator } from '../signals/RiskCalculator';
import { CandleTable } from '../tables/CandleTable';
import { IndicatorTable } from '../tables/IndicatorTable';
import { NewsList } from '../tables/NewsList';
import { TechnicalGauge } from './TechnicalGauge';
import { TechnicalTable } from './TechnicalTable';
import { TimeframeSelector } from './TimeframeSelector';

interface AnalysisWorkspaceProps {
  variant: 'stocks' | 'crypto';
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
        'rounded-sm border px-1.5 py-0.5 text-2xs font-medium transition-colors',
        active
          ? 'border-terminal-accent/60 bg-terminal-accentSoft text-terminal-accent'
          : 'border-terminal-border text-terminal-muted hover:text-terminal-text',
      )}
    >
      {children}
    </button>
  );
}

function priceDigits(value: number | null): number {
  if (value === null) return 2;
  if (value >= 1000) return 2;
  if (value >= 1) return 4;
  return 6;
}

function marketLabel(market: string, assetType: string | undefined): string {
  if (assetType === 'crypto') return 'Crypto';
  return market === 'india' ? 'India' : 'Global';
}

export function AnalysisWorkspace({ variant }: AnalysisWorkspaceProps) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = useSelectedInstrument();

  const { symbol, name, market, exchange, interval, days, instrumentId, capabilities } = selected;
  const enabled = selected.enabled;

  const [overlays, setOverlays] = useState<OverlayToggles>({
    sma: true,
    ema: false,
    bollinger: false,
  });
  const [showRsi, setShowRsi] = useState(true);
  const [showMacd, setShowMacd] = useState(true);
  const [tab, setTab] = useState('signal');
  const [watchState, setWatchState] = useState<{
    loading: boolean;
    message: string | null;
    error: string | null;
  }>({ loading: false, message: null, error: null });

  const analysis = useApi(
    (signal) => analysisService.getAnalysis({ instrumentId, interval, days }, signal),
    [instrumentId, interval, days],
    { enabled },
  );

  const indicatorSeries = useApi(
    (signal) =>
      analysisService.getIndicatorSeries(
        { instrumentId, interval, days, limit: 300 },
        signal,
      ),
    [instrumentId, interval, days],
    { enabled },
  );

  const technicals = useApi(
    (signal) => analysisService.getTechnicals({ instrumentId, interval, days }, signal),
    [instrumentId, interval, days],
    { enabled },
  );

  const news = useApi(
    (signal) => newsService.getNews({ instrumentId }, signal),
    [instrumentId],
    { enabled },
  );

  const currency = selected.currency || (market === 'india' ? 'INR' : market === 'crypto' ? 'USDT' : 'USD');
  const intraday = isIntradayInterval(interval);
  const data = analysis.data;
  const quote = selected.quote;

  const last = quote?.last ?? data?.latest.close ?? null;
  const previousClose =
    data && data.candles.length > 1 ? data.candles[data.candles.length - 2].close : null;
  const change =
    quote?.change ??
    (last !== null && previousClose !== null ? last - previousClose : null);
  const changePct =
    quote?.changePct ??
    (change !== null && previousClose ? (change / previousClose) * 100 : null);
  const changeTone = toneForNumber(change);

  function selectInstrument(instrument: Instrument) {
    setWatchState({ loading: false, message: null, error: null });
    navigate(instrumentPath(instrument, { interval, days }));
  }

  function changeTimeframe(nextInterval: string) {
    const next = new URLSearchParams(searchParams);
    next.set('interval', nextInterval);
    next.set('days', String(defaultDaysFor(nextInterval)));
    setSearchParams(next, { replace: true });
  }

  function refreshAll() {
    selected.reload();
    analysis.reload();
    indicatorSeries.reload();
    technicals.reload();
    news.reload();
  }

  async function addToWatchlist() {
    if (!instrumentId) {
      return;
    }
    setWatchState({ loading: true, message: null, error: null });
    try {
      await portfolioService.addWatchlist({ instrument_id: instrumentId });
      notifyWatchlistChanged();
      setWatchState({ loading: false, message: `${symbol} Added to Watchlist`, error: null });
    } catch (caught) {
      setWatchState({
        loading: false,
        message: null,
        error: caught instanceof Error ? caught.message : 'Could Not Add Instrument',
      });
    }
  }

  const tabs = [
    { id: 'signal', label: 'Signal' },
    { id: 'risk', label: 'Risk' },
    { id: 'indicators', label: 'Indicators' },
    { id: 'candles', label: 'Candles' },
    { id: 'news', label: 'News' },
  ];
  const activeTab = tabs.some((item) => item.id === tab) ? tab : 'signal';

  return (
    <div className="space-y-3">
      <div className="panel-surface flex flex-wrap items-center justify-between gap-2 px-2 py-1.5">
        <InstrumentSearch
          className="w-56 sm:w-64"
          placeholder="Search Ticker Or Name"
          onSelect={selectInstrument}
        />
        <div className="flex flex-wrap items-center gap-1.5">
          {watchState.message ? (
            <span className="text-2xs text-terminal-green">{watchState.message}</span>
          ) : null}
          {watchState.error ? (
            <span className="text-2xs text-terminal-red">{watchState.error}</span>
          ) : null}
          <Button size="sm" icon="refresh" onClick={refreshAll} loading={analysis.loading}>
            Refresh
          </Button>
          <Button
            size="sm"
            variant="primary"
            icon="plus"
            loading={watchState.loading}
            disabled={!instrumentId}
            onClick={addToWatchlist}
          >
            Watchlist
          </Button>
        </div>
      </div>

      {!instrumentId ? (
        <EmptyState
          title="No Instrument Selected"
          description={
            variant === 'crypto'
              ? 'Search a crypto pair or asset name above.'
              : 'Search a ticker or company name above.'
          }
          icon="search"
        />
      ) : analysis.loading && !data ? (
        <LoadingPanel label={`Loading ${symbol}`} rows={10} />
      ) : analysis.error ? (
        <ErrorState message={analysis.error} onRetry={analysis.reload} />
      ) : data ? (
        <>
          {data.warnings.length > 0 ? (
            <div className="space-y-1">
              {data.warnings.map((warning) => (
                <Notice key={warning} tone="warning">
                  {warning}
                </Notice>
              ))}
            </div>
          ) : null}

          <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <h1 className="text-lg font-semibold leading-none tracking-tight text-terminal-text">
                  {symbol}
                </h1>
                <span className="truncate text-xs text-terminal-muted">{name}</span>
                <Badge tone="accent">{exchange}</Badge>
                <Badge>{marketLabel(market, selected.instrument?.asset_type)}</Badge>
                {capabilities ? <Badge>{capabilities.provider_key}</Badge> : null}
                <Badge tone={data.is_adjusted ? 'positive' : 'warning'}>
                  {data.is_adjusted ? 'Adjusted' : 'Unadjusted'}
                </Badge>
                {data.is_stale ? <Badge tone="warning">Stale</Badge> : null}
              </div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="num text-xl font-semibold leading-none text-terminal-text">
                  {formatNumber(last, priceDigits(last))}
                  <span className="ml-1 text-2xs font-normal text-terminal-muted">{currency}</span>
                </span>
                <span
                  className={cn(
                    'num text-xs font-medium',
                    changeTone === 'positive'
                      ? 'text-terminal-green'
                      : changeTone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {change === null ? '—' : formatSignedFixed(change, changeDigits(change))}
                  {'  '}
                  {formatPercent(changePct, 2, true)}
                </span>
                <span className="text-2xs text-terminal-muted">
                  {intervalLabel(interval)} · As of {formatDate(data.as_of)}
                </span>
              </div>
            </div>

            <TimeframeSelector
              options={selected.timeframes}
              value={interval}
              onChange={changeTimeframe}
            />
          </div>

          <section className="panel-surface">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-1.5">
              <h2 className="text-xs font-semibold text-terminal-text">Technical Analysis</h2>
              <span className="truncate text-2xs text-terminal-muted">
                {technicals.data ? `${technicals.data.source} · ${intervalLabel(interval)}` : intervalLabel(interval)}
              </span>
            </header>
            <div className="px-3 py-3">
              {technicals.data ? (
                <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-3">
                  <div className="flex justify-center">
                    <TechnicalGauge label="Oscillators" summary={technicals.data.summary.oscillators} />
                  </div>
                  <div className="flex justify-center">
                    <TechnicalGauge
                      label="Summary"
                      summary={technicals.data.summary.overall}
                      size="hero"
                    />
                  </div>
                  <div className="flex justify-center">
                    <TechnicalGauge
                      label="Moving Averages"
                      summary={technicals.data.summary.moving_averages}
                    />
                  </div>
                </div>
              ) : technicals.error ? (
                <ErrorState message={technicals.error} onRetry={technicals.reload} />
              ) : (
                <LoadingPanel label="Loading Technical Summary" rows={3} />
              )}
            </div>
          </section>

          {technicals.data ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <TechnicalTable title="Oscillators" rows={technicals.data.oscillators} />
              <TechnicalTable title="Moving Averages" rows={technicals.data.moving_averages} />
            </div>
          ) : null}

          <section className="panel-surface">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-1.5">
              <div className="flex items-baseline gap-2">
                <h2 className="text-xs font-semibold text-terminal-text">Price Chart</h2>
                <span className="text-2xs text-terminal-muted">
                  {intervalLabel(interval)} · {data.candles.length} Bars
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-1">
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
                  RSI
                </ToggleChip>
                <ToggleChip active={showMacd} onClick={() => setShowMacd((value) => !value)}>
                  MACD
                </ToggleChip>
              </div>
            </header>
            <div className="px-1.5 py-1.5">
              <PriceChart
                candles={data.candles}
                series={indicatorSeries.data?.series ?? null}
                latest={data.indicators}
                overlays={overlays}
                showRsi={showRsi}
                showMacd={showMacd}
                intraday={intraday}
                height={360}
              />
            </div>
            {indicatorSeries.error ? (
              <p className="border-t border-terminal-border px-3 py-1.5 text-2xs text-terminal-amber">
                Indicator Series Unavailable · RSI and MACD Panes Hidden
              </p>
            ) : null}
          </section>

          <Tabs items={tabs} active={activeTab} onChange={setTab} />

          {activeTab === 'signal' ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <SignalCard signal={data.strategy} currency={currency} />
              <Card title="Latest Bar" subtitle={intervalLabel(interval)}>
                <dl className="divide-y divide-terminal-borderSoft">
                  <KeyValue label="Open" value={formatNumber(data.latest.open, priceDigits(last))} />
                  <KeyValue label="High" value={formatNumber(data.latest.high, priceDigits(last))} />
                  <KeyValue label="Low" value={formatNumber(data.latest.low, priceDigits(last))} />
                  <KeyValue label="Close" value={formatNumber(data.latest.close, priceDigits(last))} />
                  <KeyValue label="Volume" value={formatNumber(data.latest.volume, 0)} />
                  <KeyValue label="Prior Close" value={formatNumber(previousClose, priceDigits(last))} />
                  <KeyValue label="History" value={`${data.candles.length} Bars`} />
                  <KeyValue label="Source" value={data.source} />
                </dl>
              </Card>
            </div>
          ) : null}

          {activeTab === 'risk' ? (
            <RiskCalculator
              entry={data.strategy.entry_reference ?? data.latest.close}
              stop={data.strategy.stop_reference}
              currency={currency}
            />
          ) : null}

          {activeTab === 'indicators' ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <IndicatorPanel indicators={data.indicators} close={data.latest.close} />
              <Card title="Indicator Values" subtitle="Latest Completed Bar">
                <IndicatorTable indicators={data.indicators} />
              </Card>
            </div>
          ) : null}

          {activeTab === 'candles' ? (
            <Card
              title="Recent Candles"
              subtitle={`Last ${Math.min(30, data.candles.length)} Bars · ${intervalLabel(interval)}`}
            >
              <CandleTable candles={data.candles} limit={30} />
            </Card>
          ) : null}

          {activeTab === 'news' ? (
            <Card title="News" subtitle="Provider Records">
              {news.loading ? (
                <LoadingPanel label="Loading News" rows={4} />
              ) : news.error ? (
                <ErrorState message={news.error} onRetry={news.reload} />
              ) : (
                <NewsList items={news.data?.items ?? []} note={news.data?.note} />
              )}
            </Card>
          ) : null}

        </>
      ) : null}
    </div>
  );
}
