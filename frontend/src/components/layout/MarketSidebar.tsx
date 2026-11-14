import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../../hooks/useApi';
import { useWatchlistQuotes } from '../../hooks/useWatchlistQuotes';
import { useSelectedInstrument } from '../../contexts/SelectedInstrumentContext';
import { analysisService } from '../../services/analysisService';
import { marketService } from '../../services/marketService';
import { portfolioService } from '../../services/portfolioService';
import type { Candle, Market, WatchlistItem } from '../../types/api';
import {
  cn,
  formatCompact,
  formatDate,
  formatNumber,
  formatPercent,
  formatSignedFixed,
  toneForNumber,
} from '../../utils/format';
import { analysisPath } from '../../utils/navigation';
import { exchangeForMarket } from '../../utils/timeframes';
import { notifyWatchlistChanged } from '../../utils/events';
import { Icon } from '../common/Icon';
import { EmptyState, ErrorState, LoadingPanel } from '../common/States';
import { KeyValue } from '../common/Stat';
import { Sparkline } from '../charts/Sparkline';

const marketLabel: Record<Market, string> = {
  india: 'India',
  global: 'Global',
  crypto: 'Crypto',
};

const marketDot: Record<Market, string> = {
  india: 'bg-terminal-amber',
  global: 'bg-terminal-accent',
  crypto: 'bg-terminal-green',
};

const DAY_MS = 86_400_000;

function digitsFor(value: number | null): number {
  if (value === null) return 2;
  if (value >= 1000) return 2;
  if (value >= 1) return 4;
  return 6;
}

function signedNumber(value: number | null, digits = 2): string {
  return formatSignedFixed(value, digits);
}

function changeSince(candles: Candle[], days: number): number | null {
  if (candles.length < 2) return null;
  const last = candles[candles.length - 1];
  const cutoff = Date.parse(last.timestamp) - days * DAY_MS;
  let reference: Candle | null = null;
  for (const candle of candles) {
    if (Date.parse(candle.timestamp) <= cutoff) {
      reference = candle;
    } else {
      break;
    }
  }
  if (!reference || reference.timestamp === last.timestamp || reference.close === 0) {
    return null;
  }
  return ((last.close - reference.close) / reference.close) * 100;
}

function yearToDate(candles: Candle[]): number | null {
  if (candles.length < 2) return null;
  const last = candles[candles.length - 1];
  const lastDate = new Date(last.timestamp);
  const cutoff = Date.UTC(lastDate.getUTCFullYear(), 0, 1);
  let reference: Candle | null = null;
  for (const candle of candles) {
    if (Date.parse(candle.timestamp) <= cutoff) {
      reference = candle;
    } else {
      break;
    }
  }
  if (!reference || reference.timestamp === last.timestamp || reference.close === 0) {
    return null;
  }
  return ((last.close - reference.close) / reference.close) * 100;
}

export function MarketSidebar() {
  const navigate = useNavigate();
  const selected = useSelectedInstrument();
  const { items, quotes, loading, error, reload } = useWatchlistQuotes();
  const [addOpen, setAddOpen] = useState(false);
  const [symbol, setSymbol] = useState('');
  const [market, setMarket] = useState<Market>('india');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);

  const selectedKey = `${selected.market}:${selected.symbol}:${selected.exchange}`;

  const analysis = useApi(
    (signal) =>
      analysisService.getAnalysis(
        {
          symbol: selected.symbol,
          market: selected.market,
          exchange: selected.exchange,
          interval: selected.interval,
          days: selected.days,
        },
        signal,
      ),
    [selected.symbol, selected.market, selected.exchange, selected.interval, selected.days],
    { enabled: selected.enabled },
  );

  const daily = useApi(
    (signal) =>
      marketService.getCandles(
        {
          symbol: selected.symbol,
          market: selected.market,
          exchange: selected.exchange,
          interval: '1d',
          days: 365,
        },
        signal,
      ),
    [selected.symbol, selected.market, selected.exchange],
    { enabled: selected.enabled },
  );

  const performance = useMemo(() => {
    const candles = daily.data?.candles ?? [];
    return [
      { label: '1W', value: changeSince(candles, 7) },
      { label: '1M', value: changeSince(candles, 30) },
      { label: '3M', value: changeSince(candles, 91) },
      { label: '6M', value: changeSince(candles, 182) },
      { label: 'YTD', value: yearToDate(candles) },
      { label: '1Y', value: changeSince(candles, 365) },
    ];
  }, [daily.data]);

  const sparklineValues = useMemo(
    () => (daily.data?.candles ?? []).slice(-120).map((candle) => candle.close),
    [daily.data],
  );

  function selectInstrument(item: WatchlistItem) {
    navigate(
      analysisPath(item.symbol, item.market, item.exchange, { interval: '1d', days: 500 }),
    );
  }

  async function addInstrument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = symbol.trim().toUpperCase();
    if (!clean) {
      setFormError('Enter a symbol');
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      await portfolioService.addWatchlist({
        symbol: clean,
        market,
        exchange: exchangeForMarket(market),
      });
      setSymbol('');
      setAddOpen(false);
      notifyWatchlistChanged();
      reload();
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : 'Could Not Add Instrument');
    } finally {
      setSaving(false);
    }
  }

  async function removeInstrument(item: WatchlistItem) {
    setRemoving(`${item.market}:${item.symbol}:${item.exchange}`);
    try {
      await portfolioService.removeWatchlist({
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      notifyWatchlistChanged();
      reload();
    } catch {
      // The watchlist remains unchanged when the backend rejects the removal.
    } finally {
      setRemoving(null);
    }
  }

  const quote = selected.quote;
  const atr = analysis.data?.indicators.atr_14 ?? null;
  const rvol = analysis.data?.indicators.rvol_20 ?? null;

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
        <div className="flex items-center gap-2">
          <h2 className="text-xs font-semibold text-terminal-text">Watchlist</h2>
          <span className="num text-2xs text-terminal-muted">{items.length}</span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            aria-label="Add Instrument"
            title="Add Instrument"
            onClick={() => setAddOpen((value) => !value)}
            className="rounded p-1 text-terminal-muted hover:bg-white/[0.06] hover:text-terminal-text"
          >
            <Icon name="plus" size={14} />
          </button>
          <button
            type="button"
            aria-label="Refresh Watchlist"
            title="Refresh Watchlist"
            onClick={reload}
            className="rounded p-1 text-terminal-muted hover:bg-white/[0.06] hover:text-terminal-text"
          >
            <Icon name="refresh" size={14} />
          </button>
        </div>
      </div>

      {addOpen ? (
        <form onSubmit={addInstrument} className="space-y-1.5 border-b border-terminal-border px-3 py-2">
          <input
            value={symbol}
            onChange={(event) => setSymbol(event.target.value)}
            placeholder="Symbol"
            aria-label="Symbol"
            autoComplete="off"
            className="h-7 w-full rounded-sm border border-terminal-border bg-terminal-panelAlt px-2 text-xs text-terminal-text placeholder:text-terminal-muted/70 focus:border-terminal-accent focus:outline-none"
          />
          <div className="flex gap-1.5">
            <select
              value={market}
              onChange={(event) => setMarket(event.target.value as Market)}
              aria-label="Market"
              className="h-7 min-w-0 flex-1 rounded-sm border border-terminal-border bg-terminal-panelAlt px-1.5 text-2xs text-terminal-text focus:border-terminal-accent focus:outline-none"
            >
              <option value="india">India</option>
              <option value="global">Global</option>
              <option value="crypto">Crypto</option>
            </select>
            <button
              type="submit"
              disabled={saving}
              className="h-7 rounded-sm bg-terminal-accent px-2.5 text-2xs font-medium text-white hover:brightness-110 disabled:opacity-60"
            >
              {saving ? 'Adding…' : 'Add'}
            </button>
          </div>
          {formError ? <p className="text-2xs text-terminal-red">{formError}</p> : null}
        </form>
      ) : null}

      <div className="max-h-[42vh] min-h-[120px] overflow-y-auto">
        <div className="grid grid-cols-[minmax(0,1fr)_74px_62px_58px_16px] gap-1 border-b border-terminal-border px-3 py-1 text-2xs text-terminal-muted">
          <span>Symbol</span>
          <span className="text-right">Last</span>
          <span className="text-right">Chg</span>
          <span className="text-right">Chg%</span>
          <span />
        </div>

        {loading && quotes.length === 0 ? (
          <LoadingPanel className="px-3 py-3" label="Loading Watchlist…" rows={4} />
        ) : error ? (
          <ErrorState className="m-2" message={error} onRetry={reload} />
        ) : quotes.length === 0 ? (
          <div className="px-3 py-6 text-center">
            <p className="text-xs text-terminal-muted">Watchlist Empty</p>
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="mt-2 text-2xs text-terminal-accent hover:underline"
            >
              Add Instrument
            </button>
          </div>
        ) : (
          quotes.map((row) => {
            const tone = toneForNumber(row.change);
            const active = row.key === selectedKey;
            return (
              <div
                key={row.key}
                className={cn(
                  'group grid grid-cols-[minmax(0,1fr)_74px_62px_58px_16px] items-center gap-1 border-b border-terminal-borderSoft px-3 py-[5px] text-xs',
                  active
                    ? 'bg-[#17202e] shadow-[inset_2px_0_0_#2f6feb]'
                    : 'hover:bg-white/[0.03]',
                )}
              >
                <button
                  type="button"
                  onClick={() => selectInstrument(row.item)}
                  className="flex min-w-0 items-center gap-1.5 text-left"
                  title={`${row.item.symbol} · ${marketLabel[row.item.market]}`}
                >
                  <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', marketDot[row.item.market])} />
                  <span className="truncate font-medium text-terminal-text">{row.item.symbol}</span>
                </button>
                <span className="num text-right text-terminal-text">
                  {formatNumber(row.last, digitsFor(row.last))}
                </span>
                <span
                  className={cn(
                    'num text-right',
                    tone === 'positive'
                      ? 'text-terminal-green'
                      : tone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {signedNumber(row.change, 2)}
                </span>
                <span
                  className={cn(
                    'num text-right',
                    tone === 'positive'
                      ? 'text-terminal-green'
                      : tone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {formatPercent(row.changePct, 2, true)}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${row.item.symbol}`}
                  title={`Remove ${row.item.symbol}`}
                  disabled={removing === row.key}
                  onClick={() => {
                    void removeInstrument(row.item);
                  }}
                  className="rounded p-0.5 text-terminal-muted opacity-0 hover:text-terminal-red group-hover:opacity-100 disabled:opacity-40"
                >
                  <Icon name="close" size={11} />
                </button>
              </div>
            );
          })
        )}
      </div>

      <div className="flex-1 border-t border-terminal-border">
        {!selected.enabled ? (
          <div className="px-3 py-6 text-center text-xs text-terminal-muted">
            Select an Instrument
          </div>
        ) : selected.loading && !quote ? (
          <LoadingPanel className="px-3 py-4" label="Loading Instrument…" rows={4} />
        ) : selected.error ? (
          <ErrorState className="m-2" message={selected.error} onRetry={selected.reload} />
        ) : quote ? (
          <div>
            <div className="flex items-center justify-between px-3 pt-2">
              <div className="flex min-w-0 items-baseline gap-2">
                <span className="text-xs font-semibold text-terminal-text">{selected.symbol}</span>
                <span className="truncate text-2xs text-terminal-muted">
                  {marketLabel[selected.market]} · {selected.exchange}
                </span>
              </div>
              <button
                type="button"
                aria-label="Refresh Instrument"
                title="Refresh Instrument"
                onClick={() => {
                  selected.reload();
                  analysis.reload();
                  daily.reload();
                }}
                className="rounded p-1 text-terminal-muted hover:bg-white/[0.06] hover:text-terminal-text"
              >
                <Icon name="refresh" size={13} />
              </button>
            </div>

            <div className="flex flex-wrap items-baseline gap-x-2 px-3 pt-1">
              <span className="num text-lg font-semibold text-terminal-text">
                {formatNumber(quote.last, digitsFor(quote.last))}
              </span>
              <span
                className={cn(
                  'num text-xs',
                  toneForNumber(quote.change) === 'positive'
                    ? 'text-terminal-green'
                    : toneForNumber(quote.change) === 'negative'
                      ? 'text-terminal-red'
                      : 'text-terminal-muted',
                )}
              >
                {signedNumber(quote.change, 2)} ({formatPercent(quote.changePct, 2, true)})
              </span>
            </div>
            <p className="truncate px-3 pt-0.5 text-2xs text-terminal-muted" title={quote.source}>
              {quote.source} · {formatDate(quote.asOf)}
            </p>

            <dl className="mt-2 divide-y divide-terminal-borderSoft px-3">
              <KeyValue label="Day High" value={formatNumber(quote.high, digitsFor(quote.high))} />
              <KeyValue label="Day Low" value={formatNumber(quote.low, digitsFor(quote.low))} />
              <KeyValue label="Volume" value={formatCompact(quote.volume)} />
              <KeyValue label="ATR (14)" value={formatNumber(atr, 2)} />
              <KeyValue label="Relative Volume (20)" value={formatNumber(rvol, 2)} />
              <KeyValue
                label="Adjustment"
                value={quote.isAdjusted ? 'Adjusted' : 'Unadjusted'}
              />
            </dl>

            <div className="px-3 py-2">
              <p className="text-2xs text-terminal-muted">Performance</p>
              <div className="mt-1 grid grid-cols-3 gap-1">
                {performance.map((item) => {
                  const tone = toneForNumber(item.value);
                  return (
                    <div
                      key={item.label}
                      className={cn(
                        'rounded-sm px-1.5 py-1',
                        tone === 'positive'
                          ? 'bg-[#101c19]'
                          : tone === 'negative'
                            ? 'bg-[#1c1214]'
                            : 'bg-[#17191d]',
                      )}
                    >
                      <p className="text-2xs text-terminal-muted">{item.label}</p>
                      <p
                        className={cn(
                          'num text-xs font-medium',
                          tone === 'positive'
                            ? 'text-terminal-green'
                            : tone === 'negative'
                              ? 'text-terminal-red'
                              : 'text-terminal-muted',
                        )}
                      >
                        {formatPercent(item.value, 2, true)}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>

            <div className="px-3 pb-3">
              <Sparkline values={sparklineValues} height={54} />
              <p className="text-2xs text-terminal-muted">120 Daily Closes</p>
            </div>
          </div>
        ) : (
          <EmptyState className="m-2" title="No Quote" icon="chart" />
        )}
      </div>
    </div>
  );
}
