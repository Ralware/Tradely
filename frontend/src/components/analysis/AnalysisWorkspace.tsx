import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { apiRequest } from '../../services/api';
import { snapshotStore } from '../../services/snapshotStore';
import { isCompleteSnapshot, loadAnalyticsSnapshot } from '../../services/analyticsSnapshotLoader';
import { portfolioService } from '../../services/portfolioService';
import type { DirectionMode, Instrument } from '../../types/api';
import { changeDigits, cn, formatDate, formatNumber, formatPercent, formatSignedFixed, toneForNumber } from '../../utils/format';
import { defaultDaysFor, intervalLabel, isIntradayInterval } from '../../utils/timeframes';
import { instrumentPath } from '../../utils/navigation';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Select } from '../common/Field';
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

  const { symbol, name, market, exchange, interval, days, instrumentId, capabilities } = selected;

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
  const data = usableSnapshot?.analysis ? {
    ...usableSnapshot.analysis,
    strategy: usableSnapshot.strategy_variants?.[`${directionMode}:NONE`]
      ?? usableSnapshot.strategy_variants?.[`${directionMode}:LONG`]
      ?? usableSnapshot.strategy_variants?.[`${directionMode}:SHORT`],
  } : null;
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
          {data.warnings.length > 0 ? (
            <div className="space-y-1">
              {data.warnings.map((warning: string) => (
                <Notice key={warning} tone="warning">
                  {warning}
                </Notice>
              ))}
            </div>
          ) : null}

      <div className="tv-instrument-heading flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
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
                  {intervalLabel(displayedInterval)} · As of {formatDate(data.as_of)}
                </span>
              </div>
            </div>

            <div className="flex flex-wrap items-end gap-2">
              <Select
                label="Strategy Direction"
                value={directionMode}
                onChange={(event) => setDirectionMode(event.target.value as DirectionMode)}
                options={[
                  { value: 'long_only', label: 'Long Only' },
                  { value: 'short_only', label: 'Short Only' },
                  { value: 'long_short', label: 'Long + Short' },
                ]}
              />
              <div className="flex items-end gap-2">
                <TimeframeSelector
                  className="tv-timeframe-selector"
                  options={selected.timeframes}
                  value={interval}
                  onChange={changeTimeframe}
                />
                <span
                  className="self-center whitespace-nowrap text-2xs text-terminal-muted"
                  role="status"
                  title={manifest?.last_error ?? ''}
                >
                  {manifest?.status ?? 'MISSING'} · {manifest?.candle_count ?? 0} bars
                </span>
                <span
                  role="status"
                  className={cn(
                    'self-center inline-flex h-3 w-3 items-center justify-center text-terminal-muted transition-opacity duration-300',
                    updating ? 'opacity-100' : 'opacity-0',
                  )}
                >
                  <span
                    className="h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
                    aria-hidden="true"
                  />
                  {updating ? <span className="sr-only">Updating</span> : null}
                </span>
              </div>
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
              <SignalCard signal={data.strategy} />
            </div>
          ) : null}

          <div className="tv-analysis-tabs">
            <Tabs items={tabs} active={activeTab} onChange={setTab} />
          </div>

          {activeTab === 'risk' ? (
            <div className="tv-tab-panel">
              <RiskCalculator
                entry={data.strategy.entry_reference ?? data.latest.close}
                stop={data.strategy.stop_reference}
                direction={data.strategy.direction ?? 'LONG'}
                currency={currency}
              />
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
                <CandleTable candles={data.candles} limit={30} />
              </Card>
            </div>
          ) : null}

        </>
      ) : null}
    </div>
  );
}
