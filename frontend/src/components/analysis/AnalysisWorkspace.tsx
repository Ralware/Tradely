import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { apiRequest } from '../../services/api';
import { snapshotStore } from '../../services/snapshotStore';
import { isCompleteSnapshot, loadAnalyticsSnapshot } from '../../services/analyticsSnapshotLoader';
import { portfolioService } from '../../services/portfolioService';
import { suppressStaleStrategy } from '../../services/staleStrategy';
import type { DirectionMode, Instrument } from '../../types/api';
import { changeDigits, cn, formatDate, formatNumber, formatPercent, formatSignedFixed, toneForNumber } from '../../utils/format';
import { pricePrecisionFor, minMoveFromMetadata } from '../../utils/precision';
import { defaultDaysFor, intervalLabel, isIntradayInterval } from '../../utils/timeframes';
import { instrumentPath } from '../../utils/navigation';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Icon } from '../common/Icon';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';
import { Tabs } from '../common/Tabs';
import { PriceChart } from '../charts/PriceChart';
import type { OverlayToggles } from '../charts/PriceChart';
import { IndicatorPanel } from '../charts/IndicatorPanel';
import { InstrumentSearch } from '../instruments/InstrumentSearch';
import { SignalCard } from '../signals/SignalCard';
import { RiskCalculator } from '../signals/RiskCalculator';
import { CandleTable } from '../tables/CandleTable';
import { IndicatorTable } from '../tables/IndicatorTable';
import { TechnicalGauge } from './TechnicalGauge';
import { TechnicalTable } from './TechnicalTable';
import { TimeframeSelector } from './TimeframeSelector';

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
        'rounded border px-1.5 py-0.5 text-2xs font-medium transition-colors',
        active
          ? 'border-terminal-accent/60 bg-terminal-accentSoft text-terminal-accent'
          : 'border-terminal-border text-terminal-muted hover:text-terminal-text',
      )}
    >
      {children}
    </button>
  );
}

export function AnalysisWorkspace({
  directionMode: controlledDirectionMode,
  onDirectionModeChange,
}: {
  directionMode?: DirectionMode;
  onDirectionModeChange?: (mode: DirectionMode) => void;
} = {}) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = useSelectedInstrument();

  const { symbol, name, market, interval, days, instrumentId } = selected;

  const [overlays, setOverlays] = useState<OverlayToggles>({
    sma: false,
    ema: false,
    bollinger: false,
  });
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [localDirectionMode, setLocalDirectionMode] = useState<DirectionMode>('long_only');
  const directionMode = controlledDirectionMode ?? localDirectionMode;
  const setDirectionMode = onDirectionModeChange ?? setLocalDirectionMode;
  const [tab, setTab] = useState('risk');
  const [, forceSnapshotRender] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [loadState, setLoadState] = useState<{
    key: string;
    status: 'loading' | 'ready' | 'error';
    error?: string;
  } | null>(null);
  const [watchState, setWatchState] = useState<{
    loading: boolean;
    message: string | null;
    error: string | null;
  }>({ loading: false, message: null, error: null });

  useEffect(() => {
    if (!instrumentId) return undefined;
    const select = () => forceSnapshotRender((value) => value + 1);
    return snapshotStore.subscribe(instrumentId, interval, select);
  }, [instrumentId, interval]);

  const snapshot = instrumentId ? snapshotStore.getSnapshot(instrumentId, interval) : undefined;
  const usableSnapshot = isCompleteSnapshot(snapshot) ? snapshot : undefined;
  const snapshotKey = instrumentId ? `${instrumentId}\u0000${interval}` : '';
  const snapshotLoading = loadState?.key === snapshotKey && loadState.status === 'loading';
  const snapshotError = loadState?.key === snapshotKey && loadState.status === 'error'
    ? loadState.error ?? 'Analytics could not be loaded.'
    : null;
  const snapshotStale = Boolean(usableSnapshot && (
    usableSnapshot.analysis?.is_stale === true
    || usableSnapshot.technical_ratings?.is_stale === true
    || usableSnapshot.provenance?.data_freshness === 'stale'
  ));
  const selectedStrategy = usableSnapshot?.strategy_variants?.[`${directionMode}:NONE`]
    ?? usableSnapshot?.strategy_variants?.[`${directionMode}:LONG`]
    ?? usableSnapshot?.strategy_variants?.[`${directionMode}:SHORT`];
  const data = usableSnapshot?.analysis ? {
    ...usableSnapshot.analysis,
    is_stale: snapshotStale,
    strategy: snapshotStale && selectedStrategy && typeof selectedStrategy === 'object'
      ? suppressStaleStrategy(selectedStrategy)
      : selectedStrategy,
  } : null;
  const visibleWarnings = data?.warnings.filter(
    (warning: string) => !warning.toLowerCase().startsWith('latest candle is stale for this market'),
  ) ?? [];
  const technicals = usableSnapshot?.technical_ratings ?? null;
  const indicatorSeries = usableSnapshot?.indicator_series ?? null;
  const currency = selected.currency || (market === 'india' ? 'INR' : market === 'crypto' ? 'USDT' : 'USD');
  const quote = selected.quote;
  const displayedInterval = data?.interval ?? interval;
  const intraday = isIntradayInterval(displayedInterval);
  const manifest = instrumentId ? snapshotStore.getManifestItem(instrumentId, interval) : undefined;
  const updating = refreshing;
  const missing = !usableSnapshot;
  const error = manifest?.last_error ?? null;

  useEffect(() => {
    if (!instrumentId) return undefined;
    const identity = instrumentId;
    const timeframe = interval;
    const key = `${identity}\u0000${timeframe}`;
    const controller = new AbortController();
    let active = true;
    async function load(): Promise<void> {
      setLoadState({ key, status: 'loading' });
      try {
        const payload = await loadAnalyticsSnapshot(identity, timeframe, {
          signal: controller.signal,
          onCached: (cached) => {
            if (active) snapshotStore.setSnapshot(identity, timeframe, cached);
          },
        });
        if (!active) return;
        snapshotStore.setSnapshot(identity, timeframe, payload);
        setLoadState({ key, status: 'ready' });
      } catch (caught) {
        if (!active || controller.signal.aborted) return;
        setLoadState({
          key,
          status: 'error',
          error: caught instanceof Error ? caught.message : 'Analytics could not be loaded.',
        });
      }
    }

    void load();
    return () => {
      active = false;
      controller.abort();
    };
  }, [instrumentId, interval, loadAttempt]);

  const last = quote?.last ?? data?.latest.close ?? null;
  const priceMetadata =
    data?.price_metadata
    ?? technicals?.price_metadata
    ?? indicatorSeries?.price_metadata
    ?? selected.instrument
    ?? null;
  const pricePrecision = pricePrecisionFor(last, priceMetadata);
  const priceMinMove = minMoveFromMetadata(priceMetadata);
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

  async function refreshAll() {
    if (!instrumentId) return;
    setRefreshing(true);
    try {
      await apiRequest('/api/analytics/precompute/refresh', {
        method: 'POST', query: { instrument_id: instrumentId, interval },
      });
    } finally { setRefreshing(false); }
  }

  async function addToWatchlist() {
    if (!instrumentId) {
      return;
    }
    setWatchState({ loading: true, message: null, error: null });
    try {
      await portfolioService.addWatchlist({ instrument_id: instrumentId });
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
    { id: 'risk', label: 'Risk' },
    { id: 'indicators', label: 'Indicators' },
    { id: 'candles', label: 'Candles' },
  ];
  const activeTab = tabs.some((item) => item.id === tab) ? tab : 'risk';

  return (
    <div className="tv-technicals space-y-3">
      <div className="tv-analysis-toolbar panel-surface flex flex-wrap items-center justify-between gap-2 px-2 py-1.5">
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
          <Button size="sm" icon="refresh" onClick={() => void refreshAll()} loading={refreshing}>
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

      {snapshotError && usableSnapshot ? (
        <Notice tone="warning">Refresh failed; showing the last known-good local analytics. {snapshotError}</Notice>
      ) : null}

      {!instrumentId ? (
        <EmptyState
          title="No Instrument Selected"
          description="Search a ticker, crypto pair, or asset name above."
          icon="search"
        />
      ) : missing ? (
        <EmptyState
          title={snapshotLoading ? 'Loading Analytics' : snapshotError || manifest?.status === 'FAILED' ? 'Analytics Unavailable' : 'Loading Analytics'}
          description={snapshotError ?? error ?? `Checking local ${intervalLabel(interval)} analytics; retrieving and calculating this timeframe only if no complete local snapshot is available.`}
          icon="chart"
          action={snapshotError ? <Button size="sm" icon="refresh" onClick={() => setLoadAttempt((value) => value + 1)}>Retry</Button> : undefined}
        />
      ) : data ? (
        <>
          {error ? (
            <Notice tone="warning">
              {`Refresh issue for ${symbol}; the last complete snapshot remains available. ${error}`}
            </Notice>
          ) : null}
          {visibleWarnings.length > 0 ? (
            <div className="space-y-1">
              {visibleWarnings.map((warning: string) => (
                <Notice key={warning} tone="warning">
                  {warning}
                </Notice>
              ))}
            </div>
          ) : null}

        <div className="tv-instrument-heading flex min-w-0 flex-col gap-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <h1 className="text-lg font-semibold leading-none tracking-tight text-terminal-text">
                  {symbol}
                </h1>
                <span className="truncate text-xs text-terminal-muted">{name}</span>
              </div>
              <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <span className="num text-xl font-semibold leading-none text-terminal-text">
                  {formatNumber(last, pricePrecision)}
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
                  {change === null ? '—' : formatSignedFixed(change, changeDigits(change, pricePrecision))}
                  {'  '}
                  {formatPercent(changePct, 2, true)}
                </span>
                <span className="text-2xs text-terminal-muted">
                  {intervalLabel(displayedInterval)} · As of {formatDate(data.as_of)}
                </span>
              </div>
            </div>

            <div className="flex min-w-0 items-center gap-2">
              <div className="min-w-0 flex-1 overflow-x-auto">
                <TimeframeSelector
                  className="tv-timeframe-selector w-max"
                  options={selected.timeframes}
                  value={interval}
                  onChange={changeTimeframe}
                />
              </div>
              <span
                className="ml-auto shrink-0 whitespace-nowrap text-2xs text-terminal-muted"
                role="status"
                title={manifest?.last_error ?? ''}
              >
                {manifest?.status ?? 'MISSING'} · {manifest?.candle_count ?? 0} bars
              </span>
              <span
                role="status"
                className={cn(
                  'inline-flex h-3 w-3 shrink-0 items-center justify-center text-terminal-muted transition-opacity duration-300',
                  updating ? 'opacity-100' : 'opacity-0',
                )}
              >
                <Icon name="refresh" size={12} className="animate-spin" />
                {updating ? <span className="sr-only">Updating</span> : null}
              </span>
            </div>
          </div>

          <section className="tv-rating-overview">
            <header className="tv-rating-overview-header">
              <div>
                <h2 className="tv-rating-overview-title">Technical Ratings</h2>
                <p className="tv-rating-overview-subtitle">
                  {intervalLabel(displayedInterval)}
                  {technicals ? ` · ${technicals.source_name} · ${technicals.source_version}` : ''}
                </p>
              </div>
              <span className="tv-rating-overview-asof">As of {formatDate(technicals?.as_of ?? data.as_of)}</span>
            </header>
            <div className={cn('tv-rating-gauges transition-opacity duration-300', updating ? 'opacity-70' : 'opacity-100')}>
              {technicals ? (
                <>
                  <TechnicalGauge label="Oscillators" summary={technicals.summary.oscillators} />
                  <TechnicalGauge label="Overall" summary={technicals.summary.overall} size="hero" />
                  <TechnicalGauge label="Moving Averages" summary={technicals.summary.moving_averages} />
                </>
              ) : error ? (
                <ErrorState message={error} onRetry={() => void refreshAll()} />
              ) : (
                <LoadingPanel label="Loading TradingView Technical Rating · Pine Script v6" rows={3} />
              )}
            </div>
          </section>

          <section className="panel-surface tv-price-chart">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-1.5">
              <div className="flex items-baseline gap-2">
                <h2 className="text-xs font-semibold text-terminal-text">Price Chart</h2>
                <span className="text-2xs text-terminal-muted">
                  {intervalLabel(displayedInterval)} · {data.candles.length} Bars
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
            <div
              className={cn(
                'px-1.5 py-1.5 transition-opacity duration-300',
                updating ? 'opacity-80' : 'opacity-100',
              )}
            >
              <PriceChart
                candles={data.candles}
                series={indicatorSeries?.series ?? null}
                overlays={overlays}
                showRsi={showRsi}
                showMacd={showMacd}
                timeframe={displayedInterval}
                symbol={symbol}
                pricePrecision={pricePrecision}
                priceMinMove={priceMinMove}
                intraday={intraday}
                height={360}
              />
            </div>
          </section>

          {technicals ? (
            <div className="tv-technical-tables grid grid-cols-1 gap-3 xl:grid-cols-2">
              <TechnicalTable
                title="Moving Averages"
                rows={technicals.moving_averages}
                summary={technicals.summary.moving_averages}
              />
              <TechnicalTable
                title="Oscillators"
                rows={technicals.oscillators}
                summary={technicals.summary.oscillators}
              />
            </div>
          ) : null}

          {technicals ? (
            <div className="tv-strategy-summary">
              <SignalCard
                signal={data.strategy}
                directionMode={directionMode}
                onDirectionModeChange={setDirectionMode}
                isStale={snapshotStale}
              />
            </div>
          ) : null}

          <div className="tv-analysis-tabs">
            <Tabs items={tabs} active={activeTab} onChange={setTab} />
          </div>

          {activeTab === 'risk' ? (
            <div className="tv-tab-panel">
              {snapshotStale ? (
                <Notice tone="warning">Trade sizing is unavailable for stale reference data. Refresh successfully before using entry, stop, or risk calculations.</Notice>
              ) : (
                <RiskCalculator
                  entry={data.strategy.entry_reference ?? data.latest.close}
                  stop={data.strategy.stop_reference}
                  direction={data.strategy.direction ?? 'LONG'}
                  currency={currency}
                />
              )}
            </div>
          ) : null}

          {activeTab === 'indicators' ? (
            <div className="tv-tab-panel grid grid-cols-1 gap-3 xl:grid-cols-2">
              <IndicatorPanel indicators={data.indicators} close={data.latest.close} />
              <Card title="Indicator Values" subtitle="Latest Completed Bar">
                <IndicatorTable indicators={data.indicators} />
              </Card>
            </div>
          ) : null}

          {activeTab === 'candles' ? (
            <div className="tv-tab-panel">
              <Card
                title="Recent Candles"
                subtitle={`Last ${Math.min(30, data.candles.length)} Bars · ${intervalLabel(displayedInterval)}`}
              >
                <CandleTable candles={data.candles} limit={30} pricePrecision={pricePrecision} />
              </Card>
            </div>
          ) : null}

        </>
      ) : null}
    </div>
  );
}
