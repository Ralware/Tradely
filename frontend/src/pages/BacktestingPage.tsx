import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { backtestService } from '../services/backtestService';
import type { BacktestRequest, BacktestResult, DirectionMode, Market, StrategyConfig } from '../types/api';
import { formatNumber, formatPercent } from '../utils/format';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { Input, Select } from '../components/common/Field';
import { PageHeader } from '../components/common/PageHeader';
import { EmptyState, ErrorState, Notice } from '../components/common/States';
import { Stat } from '../components/common/Stat';
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart';
import type { TimeSeriesPoint } from '../components/charts/TimeSeriesChart';
import { ResearchSearch } from '../components/analysis/ResearchSearch';
import { TradesTable } from '../components/tables/TradesTable';

const marketOptions = [
  { value: 'india', label: 'Indian Equities' },
  { value: 'global', label: 'International Equities' },
  { value: 'crypto', label: 'Crypto Spot' },
];

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

const DEFAULT_STRATEGY: StrategyConfig = {
  sma_fast_period: 50, sma_slow_period: 200, rsi_period: 14, rsi_threshold: 50,
  adx_period: 14, min_adx: 20, atr_period: 14, initial_stop_atr: 2,
  trailing_stop_atr: 3, donchian_entry_period: 20, rvol_period: 20,
  min_rvol: 1, donchian_exit_period: 10,
};
const STRATEGY_FIELDS: Array<{ key: keyof StrategyConfig; label: string; min: number; max: number; step: number; hint: string }> = [
  { key: 'sma_fast_period', label: 'Fast SMA Period', min: 2, max: 500, step: 1, hint: 'Medium term trend filter.' },
  { key: 'sma_slow_period', label: 'Slow SMA Period', min: 3, max: 1000, step: 1, hint: 'Long term trend filter.' },
  { key: 'rsi_period', label: 'RSI Period', min: 2, max: 100, step: 1, hint: 'Momentum lookback.' },
  { key: 'rsi_threshold', label: 'RSI Confirmation', min: 1, max: 99, step: 1, hint: 'Long threshold; short uses its symmetric level.' },
  { key: 'adx_period', label: 'ADX Period', min: 2, max: 100, step: 1, hint: 'Trend strength lookback.' },
  { key: 'min_adx', label: 'Minimum ADX', min: 0, max: 100, step: 0.5, hint: 'Minimum trend strength.' },
  { key: 'atr_period', label: 'ATR Period', min: 2, max: 100, step: 1, hint: 'Volatility lookback for stops.' },
  { key: 'initial_stop_atr', label: 'Initial Stop (ATR)', min: 0.01, max: 20, step: 0.01, hint: 'Entry stop distance.' },
  { key: 'trailing_stop_atr', label: 'Trailing Stop (ATR)', min: 0.01, max: 20, step: 0.01, hint: 'Close-based trailing stop distance.' },
  { key: 'donchian_entry_period', label: 'Donchian Entry', min: 2, max: 500, step: 1, hint: 'Prior bars used for breakout.' },
  { key: 'rvol_period', label: 'Relative Volume Lookback', min: 2, max: 500, step: 1, hint: 'Compared with prior average volume.' },
  { key: 'min_rvol', label: 'Minimum Relative Volume', min: 0, max: 100, step: 0.1, hint: 'Minimum current/average volume.' },
  { key: 'donchian_exit_period', label: 'Donchian Exit', min: 2, max: 500, step: 1, hint: 'Prior bars for channel exit.' },
];

export function BacktestingPage() {
  const [symbol, setSymbol] = useState('RELIANCE');
  const [market, setMarket] = useState<Market>('india');
  const [exchange, setExchange] = useState('NSE');
  const [days, setDays] = useState('3650');
  const [directionMode, setDirectionMode] = useState<DirectionMode>('long_only');
  const [capital, setCapital] = useState('1000');
  const [riskPercent, setRiskPercent] = useState('0.5');
  const [costBps, setCostBps] = useState('2');
  const [slippageBps, setSlippageBps] = useState('0');
  const [maxPositionPercent, setMaxPositionPercent] = useState('95');
  const [strategyConfig, setStrategyConfig] = useState<StrategyConfig>(DEFAULT_STRATEGY);
  const [savedPresets, setSavedPresets] = useState<Array<{name: string; config: StrategyConfig}>>(() => {
    try { return JSON.parse(localStorage.getItem('tradely.backtest.presets') ?? '[]'); } catch { return []; }
  });
  const [presetName, setPresetName] = useState('');
  const [comparisons, setComparisons] = useState<BacktestResult[]>(() => {
    try { return JSON.parse(localStorage.getItem('tradely.backtest.results') ?? '[]'); } catch { return []; }
  });
  const [editorOpen, setEditorOpen] = useState(true);
  const strategyErrors = useMemo(() => {
    const errors: Partial<Record<keyof StrategyConfig, string>> = {};
    STRATEGY_FIELDS.forEach((field) => {
      const value = strategyConfig[field.key];
      if (!Number.isFinite(value) || value < field.min || value > field.max) errors[field.key] = `Enter a value from ${field.min} to ${field.max}.`;
      else if (field.step === 1 && !Number.isInteger(value)) errors[field.key] = 'Enter a whole number.';
    });
    if (strategyConfig.sma_fast_period >= strategyConfig.sma_slow_period) errors.sma_fast_period = 'Fast SMA must be less than slow SMA.';
    return errors;
  }, [strategyConfig]);

  const [result, setResult] = useState<BacktestResult | null>(() => comparisons[comparisons.length - 1] ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function changeMarket(next: Market) {
    setMarket(next);
    setExchange(exchangeOptions[next][0].value);
  }

  async function runBacktest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    const cleanSymbol = symbol.trim().toUpperCase();
    const parsedDays = Number(days);
    const parsedCapital = Number(capital);
    const parsedRisk = Number(riskPercent) / 100;
    const parsedCost = Number(costBps);
    const parsedSlippage = Number(slippageBps);
    const parsedMaxPosition = Number(maxPositionPercent) / 100;

    if (!cleanSymbol) {
      setError('Enter a Symbol');
      return;
    }
    if (Object.keys(strategyErrors).length > 0) {
      setError(Object.values(strategyErrors)[0] ?? 'Correct the strategy settings before running.');
      return;
    }
    if (!Number.isFinite(parsedDays) || parsedDays < 240 || parsedDays > 3650) {
      setError('History Must Be 240 to 3650 Days');
      return;
    }
    if (!Number.isFinite(parsedCapital) || parsedCapital <= 0) {
      setError('Initial Capital Must Be Positive');
      return;
    }
    if (!Number.isFinite(parsedRisk) || parsedRisk <= 0 || parsedRisk > 0.02) {
      setError('Risk per Trade Must Be Above 0 and at Most 2%');
      return;
    }
    if (!Number.isFinite(parsedCost) || parsedCost < 0) {
      setError('Commission Must Be Zero or Positive');
      return;
    }
    if (!Number.isFinite(parsedSlippage) || parsedSlippage < 0 || parsedCost + parsedSlippage > 500) {
      setError('Commission plus Slippage Must Be at Most 500 bps per Side');
      return;
    }
    if (!Number.isFinite(parsedMaxPosition) || parsedMaxPosition <= 0 || parsedMaxPosition > 1) {
      setError('Max Position Must Be Above 0 and at Most 100%');
      return;
    }

    const payload: BacktestRequest = {
      symbol: cleanSymbol,
      market,
      exchange: market === 'crypto' ? 'BINANCE' : exchange,
      interval: '1d',
      days: parsedDays,
      initial_capital: parsedCapital,
      risk_fraction: parsedRisk,
      cost_bps_per_side: parsedCost + parsedSlippage,
      commission_bps_per_side: parsedCost,
      slippage_bps_per_side: parsedSlippage,
      max_position_fraction: parsedMaxPosition,
      direction_mode: directionMode,
      strategy_config: strategyConfig,
    };

    setLoading(true);
    try {
      const completed = await backtestService.run(payload);
      setResult(completed);
      setComparisons((previous) => {
        const next = [...previous.slice(-1), completed];
        localStorage.setItem('tradely.backtest.results', JSON.stringify(next));
        return next;
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Backtest Failed');
    } finally {
      setLoading(false);
    }
  }

  const equityPoints: TimeSeriesPoint[] = useMemo(
    () =>
      (result?.equity_curve ?? []).map((point) => ({
        timestamp: point.timestamp,
        value: point.equity,
      })),
    [result],
  );

  // Visualisation only: the underwater curve is derived from equity points the
  // backend already returned. The headline figure is backend max_drawdown_pct.
  const drawdownPoints: TimeSeriesPoint[] = useMemo(() => {
    if (!result) {
      return [];
    }
    let peak = Number.NEGATIVE_INFINITY;
    return result.equity_curve.map((point) => {
      peak = Math.max(peak, point.equity);
      const drawdown = peak > 0 ? ((point.equity - peak) / peak) * 100 : 0;
      return { timestamp: point.timestamp, value: drawdown };
    });
  }, [result]);

  const profitFactor =
    result === null
      ? '—'
      : result.profit_factor === 'infinite'
        ? '∞'
        : formatNumber(result.profit_factor, 2);

  return (
    <div className="w-full px-4 py-4 lg:px-6">
      <PageHeader title="Backtesting" subtitle="Trend Breakout · Daily Bars · Costs Included" />

      <ResearchSearch />
      <Card className="mb-3" title="Daily trend breakout configuration">
        <form onSubmit={runBacktest} className="space-y-2">
          <div className="border-b border-terminal-border pb-1 text-2xs font-semibold uppercase tracking-wide text-terminal-muted">Instrument, Test Range & Execution Assumptions</div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <Input
              label="Symbol"
              value={symbol}
              onChange={(event) => setSymbol(event.target.value)}
              placeholder="RELIANCE"
              autoComplete="off"
            />
            <Select
              label="Market"
              value={market}
              onChange={(event) => changeMarket(event.target.value as Market)}
              options={marketOptions}
            />
            <Select
              label="Exchange"
              value={exchange}
              onChange={(event) => setExchange(event.target.value)}
              options={exchangeOptions[market]}
              disabled={market === 'crypto'}
            />
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
            <Input
              label="History (Days)"
              type="number"
              min={240}
              max={3650}
              step={1}
              value={days}
              onChange={(event) => setDays(event.target.value)}
              hint="240–3650"
            />
            <Input
              label="Initial Capital"
              type="number"
              min={0}
              step="any"
              value={capital}
              onChange={(event) => setCapital(event.target.value)}
            />
            <Input
              label="Risk per Trade (%)"
              type="number"
              min={0}
              max={2}
              step="any"
              value={riskPercent}
              onChange={(event) => setRiskPercent(event.target.value)}
              hint="Maximum 2%"
            />
            <Input
              label="Taker Commission per Fill (bps)"
              type="number"
              min={0}
              step="any"
              value={costBps}
              onChange={(event) => setCostBps(event.target.value)}
            />
            <Input label="Slippage per Side (bps)" type="number" min={0} max={500} step="any" value={slippageBps} onChange={(event) => setSlippageBps(event.target.value)} hint="Added to commission in execution costs." />
            <Input
              label="Max Position (%)"
              type="number"
              min={0}
              max={100}
              step="any"
              value={maxPositionPercent}
              onChange={(event) => setMaxPositionPercent(event.target.value)}
            />
          </div>
          <details open={editorOpen} onToggle={(event) => setEditorOpen(event.currentTarget.open)} className="rounded-sm border border-terminal-border bg-terminal-panel/40">
            <summary className="cursor-pointer px-2 py-1.5 text-xs font-semibold text-terminal-text">Strategy Configuration {JSON.stringify(strategyConfig) !== JSON.stringify(DEFAULT_STRATEGY) ? <span className="text-amber-400">· Modified</span> : <span className="text-terminal-muted">· Defaults</span>}</summary>
            <div className="space-y-2 border-t border-terminal-border p-2">
              {(['Trend', 'Momentum', 'Volatility', 'Entry and Exit'] as const).map((section, sectionIndex) => {
                const ranges = [[0, 2], [2, 6], [6, 9], [9, 13]][sectionIndex];
                return <details key={section} open className="rounded-sm border border-terminal-border/70 p-2">
                  <summary className="cursor-pointer text-2xs font-semibold uppercase tracking-wide text-terminal-muted">{section}</summary>
                  <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                    {STRATEGY_FIELDS.slice(ranges[0], ranges[1]).map((field) => <Input key={field.key} label={field.label} type="number" min={field.min} max={field.max} step={field.step} value={strategyConfig[field.key]} hint={field.hint} error={strategyErrors[field.key]} onChange={(event) => setStrategyConfig((current) => ({ ...current, [field.key]: event.target.value === '' ? 0 : Number(event.target.value) }))} />)}
                  </div>
                </details>;
              })}
              <div className="flex flex-wrap items-end gap-2">
                <Button type="button" variant="secondary" onClick={() => setStrategyConfig(DEFAULT_STRATEGY)}>Reset to Defaults</Button>
                <Input label="Preset Name" value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="My configuration" />
                <Button type="button" variant="secondary" onClick={() => {
                  if (!presetName.trim()) { setError('Enter a name for this configuration'); return; }
                  const next = [...savedPresets.filter((preset) => preset.name !== presetName.trim()), { name: presetName.trim(), config: strategyConfig }];
                  setSavedPresets(next); localStorage.setItem('tradely.backtest.presets', JSON.stringify(next)); setPresetName('');
                }}>Save Preset</Button>
              </div>
              {savedPresets.map((preset) => <div key={preset.name} className="flex flex-wrap items-center gap-2 text-2xs">
                <span className="min-w-24 text-terminal-text">{preset.name}</span>
                <Button type="button" variant="ghost" onClick={() => setStrategyConfig(preset.config)}>Load</Button>
                <Button type="button" variant="ghost" onClick={() => { setPresetName(`${preset.name} copy`); setStrategyConfig(preset.config); }}>Duplicate</Button>
                <Button type="button" variant="ghost" onClick={() => { const next = savedPresets.filter((item) => item.name !== preset.name); setSavedPresets(next); localStorage.setItem('tradely.backtest.presets', JSON.stringify(next)); }}>Delete</Button>
              </div>)}
            </div>
          </details>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" icon="flask" loading={loading}>
              Run Backtest
            </Button>
            <span className="text-2xs text-terminal-muted">Daily Bars Only</span>
            <span className="text-2xs text-terminal-muted">Execution assumptions: capital, risk, max position, commission and slippage are configured above.</span>
          </div>
        </form>

        {error ? <ErrorState className="mt-2" message={error} /> : null}
      </Card>

      {loading ? (
        <Card>
          <EmptyState title="Running Backtest" description="Fetching history and replaying the strategy." icon="flask" />
        </Card>
      ) : result ? (
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Net Return"
              value={formatPercent(result.net_return_pct, 2, true)}
              tone={result.net_return_pct > 0 ? 'positive' : result.net_return_pct < 0 ? 'negative' : 'neutral'}
              hint={`Final Equity ${formatNumber(result.final_equity, 2)}`}
            />
            <Stat label="Trades" value={String(result.trade_count)} hint={`Win Rate ${formatPercent(result.win_rate_pct)}`} />
            <Stat label="Gross P/L" value={formatNumber(result.gross_pnl, 2)} />
            <Stat label="Maker Fees" value={formatNumber(result.total_maker_fees, 2)} hint="No passive orders in this strategy" />
            <Stat label="Taker Fees" value={formatNumber(result.total_taker_fees, 2)} />
            <Stat label="Total Fees" value={formatNumber(result.total_fees, 2)} />
            <Stat label="Net P/L" value={formatNumber(result.net_profit_loss, 2)} tone={result.net_profit_loss >= 0 ? 'positive' : 'negative'} hint="After modeled execution costs" />
            <Stat label="Average Winner" value={formatNumber(result.average_winning_trade, 2)} hint="Net of costs" />
            <Stat label="Average Loser" value={formatNumber(result.average_losing_trade, 2)} hint="Net of costs" />
            <Stat label="Net Profit Factor" value={profitFactor} hint="Net gains divided by net losses" />
            <Stat
              label="Max Drawdown"
              value={formatPercent(result.max_drawdown_pct)}
              tone="negative"
              hint="Backend Computed"
            />
            <Stat
              label="Expectancy per Trade"
              value={formatNumber(result.expectancy_per_trade, 2)}
              hint="Net of Costs"
            />
            <Stat label="Sharpe (Annualised)" value={formatNumber(result.sharpe_daily_annualized, 2)} hint="Daily Returns" />
            <Stat label="Sortino (Annualised)" value={formatNumber(result.sortino_daily_annualized, 2)} hint="Daily Returns" />
            <Stat
              label="Costs per Side"
              value={`${formatNumber(result.cost_bps_per_side, 2)} bps`}
              hint={result.data_adjusted ? 'Adjusted Data' : 'Unadjusted Data'}
            />
          </div>

          <div className="grid grid-cols-1 gap-3 xl:grid-cols-12">
            <Card
              className="xl:col-span-7"
              title="Equity Curve"
              subtitle={`${result.strategy} · ${
                result.direction_mode === 'short_only'
                  ? 'Short Only'
                  : result.direction_mode === 'long_short'
                    ? 'Long + Short'
                    : 'Long Only'
              } · ${result.strategy_version} · ${result.source}`}
            >
              <TimeSeriesChart
                points={equityPoints}
                height={240}
                color="#26a69a"
                baseline={result.initial_capital}
                valueFormatter={(value) => formatNumber(value, 2)}
                ariaLabel="Backtest Equity Curve"
              />
            </Card>
            <Card className="xl:col-span-5" title="Drawdown" subtitle="Derived from Backend Equity Points">
              <TimeSeriesChart
                points={drawdownPoints}
                height={240}
                color="#ef5350"
                baseline={0}
                valueFormatter={(value) => `${formatNumber(value, 2)}%`}
                ariaLabel="Backtest Drawdown Curve"
              />
            </Card>
          </div>

          <Card title="Trades" subtitle={`${result.symbol} · ${result.market} · ${result.trade_count} Round Trips`}>
            <TradesTable trades={result.trades} />
          </Card>

          <Card title="Strategy Configuration Used" subtitle={`${result.strategy_version} · ${result.executed_at ?? ''}`}>
            <div className="grid gap-1 text-2xs sm:grid-cols-3 lg:grid-cols-5">
              {STRATEGY_FIELDS.map((field) => <div key={field.key} className="rounded-sm border border-terminal-border px-2 py-1"><span className="text-terminal-muted">{field.label}</span><strong className="ml-2 text-terminal-text">{result.strategy_config[field.key]}</strong></div>)}
            </div>
            <div className="mt-2 grid gap-1 text-2xs sm:grid-cols-2 lg:grid-cols-4">
              {Object.entries({ 'Fast SMA': 'sma_fast', 'Slow SMA': 'sma_slow', RSI: 'rsi', ADX: 'adx', ATR: 'atr', 'Donchian Entry Level': 'donchian_entry', 'Donchian Exit Level': 'donchian_exit', 'Relative Volume': 'relative_volume' }).map(([label, key]) => <div key={key} className="rounded-sm border border-terminal-border/70 px-2 py-1"><span className="text-terminal-muted">Latest {label}</span><strong className="ml-2 text-terminal-text">{formatNumber(result.strategy_indicators[key] ?? null, 2)}</strong></div>)}
            </div>
            <div className="mt-2 text-2xs text-terminal-muted">{result.date_range?.start} — {result.date_range?.end} · {result.source} · {result.data_adjusted ? 'Adjusted' : 'Unadjusted'} data · Capital {result.execution_assumptions?.initial_capital} · Risk {Number(result.execution_assumptions?.risk_fraction ?? 0) * 100}% · Max position {Number(result.execution_assumptions?.max_position_fraction ?? 0) * 100}% · Commission {result.execution_assumptions?.commission_bps_per_side} bps + slippage {result.execution_assumptions?.slippage_bps_per_side} bps per side · {result.direction_mode}</div>
          </Card>
          {comparisons.length > 1 && <Card title="Backtest Comparison" subtitle="Only equivalent symbol, date and execution conditions should be compared.">
            <div className="overflow-x-auto"><table className="w-full text-left text-2xs"><thead><tr className="text-terminal-muted"><th className="p-1">Metric / Parameter</th>{comparisons.map((item, i) => <th key={`${item.executed_at}-${i}`} className="p-1">Run {i + 1} · {item.symbol}</th>)}</tr></thead><tbody>
              {[{ label: 'Net return', value: (item: BacktestResult) => formatPercent(item.net_return_pct, 2, true) }, { label: 'Trades', value: (item: BacktestResult) => String(item.trade_count) }, { label: 'Win rate', value: (item: BacktestResult) => formatPercent(item.win_rate_pct) }, { label: 'Profit factor', value: (item: BacktestResult) => item.profit_factor === 'infinite' ? '∞' : formatNumber(item.profit_factor, 2) }, { label: 'Max drawdown', value: (item: BacktestResult) => formatPercent(item.max_drawdown_pct) }].map((metric) => <tr key={metric.label} className="border-t border-terminal-border"><td className="p-1">{metric.label}</td>{comparisons.map((item, i) => <td key={i} className="p-1">{metric.value(item)}</td>)}</tr>)}
              {STRATEGY_FIELDS.map((field) => <tr key={field.key} className="border-t border-terminal-border"><td className="p-1">{field.label}</td>{comparisons.map((item, i) => <td key={i} className="p-1">{item.strategy_config[field.key]}</td>)}</tr>)}
            </tbody></table></div>
            {comparisons.length === 2 && (comparisons[0].symbol !== comparisons[1].symbol || comparisons[0].market !== comparisons[1].market || comparisons[0].date_range?.start !== comparisons[1].date_range?.start || comparisons[0].date_range?.end !== comparisons[1].date_range?.end || comparisons[0].source !== comparisons[1].source || comparisons[0].data_adjusted !== comparisons[1].data_adjusted || comparisons[0].direction_mode !== comparisons[1].direction_mode || JSON.stringify(comparisons[0].execution_assumptions) !== JSON.stringify(comparisons[1].execution_assumptions)) && <p className="mt-2 text-2xs text-amber-400">Test conditions differ; results are not directly equivalent.</p>}
          </Card>}

          {result.limitations.length > 0 ? (
            <Card title="Model Limitations">
              <ul className="list-disc space-y-0.5 pl-4 text-2xs leading-relaxed text-terminal-muted">
                {result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      ) : (
        <Card>
          <EmptyState title="No Backtest Run" description="Configure a symbol and run the simulation." icon="flask" />
        </Card>
      )}

      <Notice className="mt-3">Historical Simulation · Not a Forecast</Notice>
    </div>
  );
}
