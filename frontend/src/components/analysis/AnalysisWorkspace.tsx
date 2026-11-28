import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { apiRequest } from '../../services/api';
import { analyticsViewStore } from '../../services/analyticsViewStore';
import { snapshotStore } from '../../services/snapshotStore';
import { invalidateSnapshotValidation, isCompleteSnapshot, loadAnalyticsSnapshot } from '../../services/analyticsSnapshotLoader';
import { portfolioService } from '../../services/portfolioService';
import { marketService } from '../../services/marketService';
import { createCandlePollController, type PolledCandleState } from '../../services/candlePolling';
import { changeDigits, cn, formatDate, formatNumber, formatPercent, formatSignedFixed, toneForNumber } from '../../utils/format';
import { pricePrecisionFor, minMoveFromMetadata } from '../../utils/precision';
import { defaultDaysFor, intervalLabel, isIntradayInterval, pollDaysFor } from '../../utils/timeframes';
import { resolvePreviousClose } from '../charts/candleReconcile';
import { Button } from '../common/Button';
import { Icon } from '../common/Icon';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';
import { PriceChart } from '../charts/PriceChart';
import type { OverlayToggles } from '../charts/PriceChart';
import { TechnicalGauge } from './TechnicalGauge';
import { TechnicalTable } from './TechnicalTable';
import { TimeframeSelector } from './TimeframeSelector';

function technicalRefreshInterval(interval: string): number {
  switch (interval) {
    case '1m': return 20_000;
    case '3m': return 30_000;
    case '5m': return 45_000;
    case '15m':
    case '30m': return 60_000;
    case '45m':
    case '1h': return 2 * 60_000;
    case '2h':
    case '4h':
    case '6h':
    case '8h':
    case '12h': return 5 * 60_000;
    case '1d':
    case '3d': return 15 * 60_000;
    case '1wk':
    case '1w': return 30 * 60_000;
    case '1mo':
    case '1M': return 60 * 60_000;
    default: return 5 * 60_000;
  }
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

export function AnalysisWorkspace() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = useSelectedInstrument();

  const { symbol, name, market, exchange, interval, days, instrumentId } = selected;

  const [overlays, setOverlays] = useState<OverlayToggles>(
    () => analyticsViewStore.get().overlays,
  );
  const [showRsi, setShowRsi] = useState(() => analyticsViewStore.get().showRsi);
  const [showMacd, setShowMacd] = useState(() => analyticsViewStore.get().showMacd);
  const [polledState, setPolledState] = useState<PolledCandleState | null>(null);
  const [, forceSnapshotRender] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const forceNextLoadRef = useRef(false);
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

  // View preferences survive navigation because they live in the shared store,
  // not in this component's local state.
  useEffect(() => {
    analyticsViewStore.update({ overlays });
  }, [overlays]);
  useEffect(() => {
    analyticsViewStore.update({ showRsi });
  }, [showRsi]);
  useEffect(() => {
    analyticsViewStore.update({ showMacd });
  }, [showMacd]);
  useEffect(() => {
    if (instrumentId) {
      analyticsViewStore.setSelection({ instrumentId, interval, days });
    }
  }, [instrumentId, interval, days]);

  // Technical ratings and indicators refresh at a slower, timeframe-aware
  // cadence from the newest provider-confirmed candle; the chart's forming
  // OHLCV is polled independently below.
  useEffect(() => {
    if (!instrumentId) return undefined;
    const refreshIfVisible = () => {
      if (!document.hidden) setLoadAttempt((value) => value + 1);
    };
    const timer = window.setInterval(
      refreshIfVisible,
      technicalRefreshInterval(interval),
    );
    document.addEventListener('visibilitychange', refreshIfVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', refreshIfVisible);
    };
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
  const data = usableSnapshot?.analysis ? { ...usableSnapshot.analysis, is_stale: snapshotStale } : null;
  const visibleWarnings = data?.warnings.filter(
    (warning: string) => !warning.toLowerCase().startsWith('latest candle is stale for this market'),
  ) ?? [];
  const technicals = usableSnapshot?.technical_ratings ?? null;
  const indicatorSeries = usableSnapshot?.indicator_series ?? null;
  const currency = selected.currency || (market === 'india' ? 'INR' : market === 'crypto' ? 'USDT' : 'USD');
  const quote = selected.quote;
  const candleKey = `${instrumentId}\u0000${interval}`;
  const activePolledState = polledState?.key === candleKey ? polledState : null;
  const activeFormingCandle = activePolledState?.formingCandle ?? null;
  const activePolledCandles = useMemo(
    () => activePolledState?.candles ?? [],
    [activePolledState],
  );
  const activePollSequence = activePolledState?.sequence ?? 0;
  const activeLiveQuote = quote && !quote.isStale ? quote : null;
  const displayedInterval = data?.interval ?? interval;
  const intraday = isIntradayInterval(displayedInterval);
  const manifest = instrumentId ? snapshotStore.getManifestItem(instrumentId, interval) : undefined;
  const updating = refreshing || (snapshotLoading && Boolean(usableSnapshot));
  const missing = !usableSnapshot;
  const error = manifest?.last_error ?? null;

  // Provider candle data supplies the authoritative open, accumulated high/low,
  // close, and cumulative volume. One one-second poll feeds both the confirmed
  // tail and the forming bar through the reconciler; it is aborted on any
  // instrument/timeframe change and never starts a second loop.
  useEffect(() => {
    if (!instrumentId || !symbol || !exchange) return undefined;
    const key = `${instrumentId}\u0000${interval}`;
    const controller = createCandlePollController({
      key,
      intervalMs: 1_000,
      shouldPoll: () => !document.hidden,
      fetch: (signal) => marketService.getCandles(
        {
          instrumentId,
          symbol,
          market,
          exchange,
          interval,
          days: pollDaysFor(interval),
          refreshLatest: true,
        },
        signal,
        { force: true, refreshLatest: true, timeoutMs: 8_000 },
      ),
      onUpdate: (state) => setPolledState(state),
      onContractMismatch: (message) => {
        if (import.meta.env.DEV) {
          console.warn(`[candle-poll] ${key}: ${message}`);
        }
      },
      // A failed poll keeps the last valid state; the chart never blanks.
      onError: () => undefined,
    });
    controller.start();
    const onVisibilityChange = () => {
      if (!document.hidden) void controller.pollOnce();
    };
    document.addEventListener('visibilitychange', onVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      controller.stop();
    };
  }, [instrumentId, symbol, market, exchange, interval]);

  useEffect(() => {
    if (!instrumentId) return undefined;
    const identity = instrumentId;
    const timeframe = interval;
    const key = `${identity}\u0000${timeframe}`;
    const controller = new AbortController();
    let active = true;
    const forceRefresh = forceNextLoadRef.current;
    forceNextLoadRef.current = false;
    async function load(): Promise<void> {
      setLoadState({ key, status: 'loading' });
      try {
        const payload = await loadAnalyticsSnapshot(identity, timeframe, {
          signal: controller.signal,
          forceRefresh,
          refreshLatest: true,
          reuseRecentlyValidated: true,
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

  const latestPolledCandle = activePolledCandles.length
    ? activePolledCandles[activePolledCandles.length - 1]
    : null;
  const last = activeFormingCandle?.close
    ?? activeLiveQuote?.last
    ?? latestPolledCandle?.close
    ?? data?.latest.close
    ?? null;
  const priceMetadata =
    data?.price_metadata
    ?? technicals?.price_metadata
    ?? indicatorSeries?.price_metadata
    ?? selected.instrument
    ?? null;
  const pricePrecision = pricePrecisionFor(last, priceMetadata);
  const priceMinMove = minMoveFromMetadata(priceMetadata);
  // While a forming bar is active the latest completed close is the prior
  // close; without one it is the bar before the latest completed candle.
  const previousClose = useMemo(() => resolvePreviousClose({
    snapshotCandles: data?.candles ?? [],
    polledCandles: activePolledCandles,
    formingCandle: activeFormingCandle,
    interval: displayedInterval,
    market,
    now: Math.floor(Date.now() / 1000),
  }), [data?.candles, activePolledCandles, activeFormingCandle, displayedInterval, market]);
  const change =
    activeLiveQuote?.change ??
    quote?.change ??
    (last !== null && previousClose !== null ? last - previousClose : null);
  const changePct =
    activeLiveQuote?.changePct ??
    quote?.changePct ??
    (change !== null && previousClose ? (change / previousClose) * 100 : null);
  const changeTone = toneForNumber(change);

  function changeTimeframe(nextInterval: string) {
    const next = new URLSearchParams(searchParams);
    next.set('interval', nextInterval);
    next.set('days', String(defaultDaysFor(nextInterval)));
    setSearchParams(next, { replace: true });
  }

  async function refreshAll() {
    if (!instrumentId) return;
    setRefreshing(true);
    setRefreshError(null);
    try {
      await apiRequest('/api/analytics/precompute/refresh', {
        method: 'POST', query: { instrument_id: instrumentId, interval },
      });
      // A deliberate refresh must ignore both the navigation validation window
      // and any cached local bundle, then replace the chart in place.
      invalidateSnapshotValidation(instrumentId, interval);
      forceNextLoadRef.current = true;
      setLoadAttempt((value) => value + 1);
    } catch (caught) {
      setRefreshError(caught instanceof Error ? caught.message : 'Refresh failed.');
    } finally {
      setRefreshing(false);
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

  return (
    <div className="tv-technicals space-y-3">

      {snapshotError && usableSnapshot ? (
        <Notice tone="warning">Refresh failed; showing the last known-good local analytics. {snapshotError}</Notice>
      ) : null}

      {refreshError ? (
        <Notice tone="negative">Could not refresh analytics. {refreshError}</Notice>
      ) : null}

      {!instrumentId ? (
        <EmptyState
          title="No Instrument Selected"
          description="Search a ticker, crypto pair, or asset name in the top bar."
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

        <div className="tv-instrument-heading flex min-w-0 flex-wrap items-start justify-between gap-x-4 gap-y-2">
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

            <div className="ml-auto flex shrink-0 items-center gap-1.5">
              {watchState.message ? (
                <span role="status" className="mr-1 text-2xs text-terminal-green">{watchState.message}</span>
              ) : null}
              {watchState.error ? (
                <span role="alert" className="mr-1 text-2xs text-terminal-red">{watchState.error}</span>
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

            <div className="flex min-w-0 basis-full items-center gap-2">
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
              <span
                className="tv-rating-overview-asof"
                title={`Latest completed candle: ${formatDate(technicals?.as_of ?? data.as_of)}`}
              >
                Updated {formatDate(technicals?.calculation_timestamp ?? usableSnapshot?.generated_at ?? data.as_of)}
              </span>
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
                instrumentId={instrumentId}
                timeframe={displayedInterval}
                symbol={symbol}
                pricePrecision={pricePrecision}
                priceMinMove={priceMinMove}
                intraday={intraday}
                formingCandle={activeFormingCandle}
                polledCandles={activePolledCandles}
                pollSequence={activePollSequence}
                market={market}
                livePrice={activeFormingCandle?.close ?? activeLiveQuote?.last ?? null}
                height={480}
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

        </>
      ) : null}
    </div>
  );
}
