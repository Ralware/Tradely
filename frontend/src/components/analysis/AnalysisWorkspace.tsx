import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useApi } from '../../hooks/useApi';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { analysisService } from '../../services/analysisService';
import type { PrefetchResult } from '../../services/analysisService';
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
import { TechnicalDistribution } from './TechnicalDistribution';
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

export function AnalysisWorkspace() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = useSelectedInstrument();

  const { symbol, name, market, exchange, interval, days, instrumentId, capabilities } = selected;
  const enabled = selected.enabled;

  const [overlays, setOverlays] = useState<OverlayToggles>({
    sma: false,
    ema: false,
    bollinger: false,
  });
  const [showRsi, setShowRsi] = useState(false);
  const [showMacd, setShowMacd] = useState(false);
  const [directionMode, setDirectionMode] = useState<DirectionMode>('long_only');
  const [tab, setTab] = useState('risk');
  const [prefetchState, setPrefetchState] = useState<PrefetchResult>({
    total: 0,
    completed: 0,
    failures: [],
  });
  const forceRefreshNext = useRef(false);
  const retryController = useRef<AbortController | null>(null);
  const [watchState, setWatchState] = useState<{
    loading: boolean;
    message: string | null;
    error: string | null;
  }>({ loading: false, message: null, error: null });

  const analysis = useApi(
    (signal) => {
      const forceRefresh = forceRefreshNext.current;
      forceRefreshNext.current = false;
      return analysisService.getAnalyticsSnapshot(
        { instrumentId, interval, days, directionMode },
        signal,
        { forceRefresh },
      );
    },
    [instrumentId, interval, days, directionMode],
    {
      enabled,
      keepPreviousData: true,
      keepPreviousDataKey: `${instrumentId}:${interval}:${days}:${directionMode}`,
      keepPreviousDataScopeKey: instrumentId,
      getCachedData: () => analysisService.getCachedAnalyticsSnapshot({ instrumentId, interval, days, directionMode }),
    },
  );

  const snapshot = analysis.data;
  const data = snapshot?.analysis ?? null;
  const technicals = snapshot?.technical_ratings ?? null;
  const indicatorSeries = snapshot?.indicator_series ?? null;
  const currency = selected.currency || (market === 'india' ? 'INR' : market === 'crypto' ? 'USDT' : 'USD');
  const quote = selected.quote;
  const displayedInterval = data?.interval ?? interval;
  const intraday = isIntradayInterval(displayedInterval);
  const switchingSnapshot = analysis.isPreviousData;
  const updating = analysis.refreshing || switchingSnapshot;

  useEffect(() => {
    if (!enabled || !instrumentId || !snapshot || snapshot.interval !== interval) {
      return undefined;
    }

    const alternateTimeframes = selected.timeframes
      .filter((timeframe) => timeframe.id !== interval)
      .map((timeframe) => timeframe.id);
    const controller = new AbortController();
    setPrefetchState({ total: alternateTimeframes.length, completed: 0, failures: [] });
    void analysisService.prefetchTimeframes(
      { instrumentId, interval, days, directionMode },
      alternateTimeframes,
      controller.signal,
      setPrefetchState,
    ).then((result) => {
      if (!controller.signal.aborted) setPrefetchState(result);
    });

    return () => controller.abort();
  }, [snapshot?.snapshot_id, days, directionMode, enabled, instrumentId, interval, selected.timeframes]);

  useEffect(() => () => {
    retryController.current?.abort();
    retryController.current = null;
  }, [instrumentId, interval]);

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
    if (!instrumentId) return;
    analysisService.invalidateInstrumentCache(instrumentId);
    forceRefreshNext.current = true;
    selected.reload();
    analysis.reload();
  }

  async function retryTimeframe(intervalToRetry: string) {
    if (!instrumentId) return;
    const timeframe = selected.timeframes.find((item) => item.id === intervalToRetry);
    if (!timeframe) return;
    retryController.current?.abort();
    const controller = new AbortController();
    retryController.current = controller;
    try {
      await analysisService.getAnalyticsSnapshot(
        { instrumentId, interval: intervalToRetry, days: timeframe.days, directionMode },
        controller.signal,
        { prefetch: true },
      );
      if (!controller.signal.aborted) {
        setPrefetchState((current) => ({
          ...current,
          failures: current.failures.filter((failure) => failure.interval !== intervalToRetry),
        }));
      }
    } catch (caught) {
      if (!controller.signal.aborted) {
        setPrefetchState((current) => ({
          ...current,
          failures: [
            ...current.failures.filter((failure) => failure.interval !== intervalToRetry),
            {
              interval: intervalToRetry,
              error: caught instanceof Error ? caught.message : 'Timeframe preparation failed',
            },
          ],
        }));
      }
    }
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
          description="Search a ticker, crypto pair, or asset name above."
          icon="search"
        />
      ) : analysis.loading && !data ? (
        <LoadingPanel label={`Loading ${symbol}`} rows={10} />
      ) : !data && analysis.error ? (
        <ErrorState message={analysis.error} onRetry={analysis.reload} />
      ) : data ? (
        <>
          {analysis.error ? (
            <Notice tone="warning">
              {switchingSnapshot
                ? `Could Not Load ${intervalLabel(interval)} · Still showing the last complete ${intervalLabel(displayedInterval)} snapshot. ${analysis.error}`
                : `Could Not Refresh ${symbol} · ${analysis.error}`}
            </Notice>
          ) : switchingSnapshot ? (
            <Notice tone="neutral">
              Preparing {intervalLabel(interval)} · Keeping the complete {intervalLabel(displayedInterval)} snapshot visible until the new timeframe is ready.
            </Notice>
          ) : null}
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
                  options={selected.timeframes}
                  value={interval}
                  onChange={changeTimeframe}
                />
                <span
                  className="self-center whitespace-nowrap text-2xs text-terminal-muted"
                  role="status"
                  title={prefetchState.failures.map((failure) => `${failure.interval}: ${failure.error}`).join(' · ')}
                >
                  {switchingSnapshot
                    ? `Loading ${intervalLabel(interval)} · showing ${intervalLabel(displayedInterval)}`
                    : prefetchState.failures.length > 0
                      ? `${prefetchState.failures.length} timeframe${prefetchState.failures.length === 1 ? '' : 's'} unavailable`
                      : prefetchState.total === 0 || prefetchState.completed >= prefetchState.total
                        ? `Prepared ${Math.min(selected.timeframes.length, prefetchState.completed + 1)}/${selected.timeframes.length}`
                        : `Preparing ${Math.min(selected.timeframes.length, prefetchState.completed + 1)}/${selected.timeframes.length}`}
                </span>
                {prefetchState.failures.map((failure) => (
                  <button
                    key={failure.interval}
                    type="button"
                    onClick={() => void retryTimeframe(failure.interval)}
                    className="self-center text-2xs text-terminal-amber underline decoration-terminal-amber/40 underline-offset-2 hover:text-terminal-text"
                  >
                    Retry {failure.interval}
                  </button>
                ))}
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

          <section className="panel-surface">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-1.5">
              <div>
                <h2 className="text-xs font-semibold text-terminal-text">Technical Ratings Overview</h2>
                <p className="mt-0.5 text-2xs text-terminal-muted">TradingView TechnicalRating v3 · Pine Script v6 · {intervalLabel(displayedInterval)}</p>
              </div>
              <span className="truncate text-2xs text-terminal-muted">{technicals?.source_name} · {technicals?.source_version}</span>
            </header>
            <div className={cn('px-3 py-3 transition-opacity duration-300', updating ? 'opacity-70' : 'opacity-100')}>
              {technicals ? (
                <div className="grid grid-cols-1 items-end gap-4 sm:grid-cols-3">
                  <div className="flex justify-center">
                    <TechnicalGauge label="Oscillators" summary={technicals.summary.oscillators} />
                  </div>
                  <div className="flex justify-center">
                    <TechnicalGauge label="Overall" summary={technicals.summary.overall} size="hero" />
                  </div>
                  <div className="flex justify-center">
                    <TechnicalGauge label="Moving Averages" summary={technicals.summary.moving_averages} />
                  </div>
                </div>
              ) : analysis.error ? (
                <ErrorState message={analysis.error} onRetry={analysis.reload} />
              ) : (
                <LoadingPanel label="Loading TradingView Technical Rating · Pine Script v6" rows={3} />
              )}
            </div>
          </section>

          <section className="panel-surface">
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
                intraday={intraday}
                height={360}
              />
            </div>
          </section>

          {technicals ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <TechnicalTable
                title="Moving Average Analysis"
                rows={technicals.moving_averages}
                summary={technicals.summary.moving_averages}
              />
              <TechnicalTable
                title="Oscillator Analysis"
                rows={technicals.oscillators}
                summary={technicals.summary.oscillators}
              />
            </div>
          ) : null}

          {technicals ? (
            <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
              <TechnicalDistribution summary={technicals.summary} />
              <SignalCard signal={data.strategy} />
            </div>
          ) : null}

          <Tabs items={tabs} active={activeTab} onChange={setTab} />

          {activeTab === 'risk' ? (
            <RiskCalculator
              entry={data.strategy.entry_reference ?? data.latest.close}
              stop={data.strategy.stop_reference}
              direction={data.strategy.direction ?? 'LONG'}
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
              subtitle={`Last ${Math.min(30, data.candles.length)} Bars · ${intervalLabel(displayedInterval)}`}
            >
              <CandleTable candles={data.candles} limit={30} />
            </Card>
          ) : null}

        </>
      ) : null}
    </div>
  );
}
