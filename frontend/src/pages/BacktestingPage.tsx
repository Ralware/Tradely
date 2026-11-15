import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { backtestService } from '../services/backtestService';
import type { BacktestRequest, BacktestResult, DirectionMode, Market } from '../types/api';
import { formatNumber, formatPercent } from '../utils/format';
import { Button } from '../components/common/Button';
import { Card } from '../components/common/Card';
import { Input, Select } from '../components/common/Field';
import { PageHeader } from '../components/common/PageHeader';
import { EmptyState, ErrorState, Notice } from '../components/common/States';
import { Stat } from '../components/common/Stat';
import { TimeSeriesChart } from '../components/charts/TimeSeriesChart';
import type { TimeSeriesPoint } from '../components/charts/TimeSeriesChart';
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

export function BacktestingPage() {
  const [symbol, setSymbol] = useState('RELIANCE');
  const [market, setMarket] = useState<Market>('india');
  const [exchange, setExchange] = useState('NSE');
  const [days, setDays] = useState('3650');
  const [directionMode, setDirectionMode] = useState<DirectionMode>('long_only');
  const [capital, setCapital] = useState('100000');
  const [riskPercent, setRiskPercent] = useState('0.5');
  const [costBps, setCostBps] = useState('15');
  const [maxPositionPercent, setMaxPositionPercent] = useState('95');

  const [result, setResult] = useState<BacktestResult | null>(null);
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
    const parsedMaxPosition = Number(maxPositionPercent) / 100;

    if (!cleanSymbol) {
      setError('Enter a Symbol');
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
      setError('Cost per Side Must Be Zero or Positive');
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
      cost_bps_per_side: parsedCost,
      max_position_fraction: parsedMaxPosition,
      direction_mode: directionMode,
    };

    setLoading(true);
    try {
      setResult(await backtestService.run(payload));
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

      <Card className="mb-3" title="Configuration">
        <form onSubmit={runBacktest} className="space-y-2">
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
              min={1}
              step="any"
              value={capital}
              onChange={(event) => setCapital(event.target.value)}
            />
            <Input
              label="Risk per Trade (%)"
              type="number"
              min={0.01}
              max={2}
              step="0.01"
              value={riskPercent}
              onChange={(event) => setRiskPercent(event.target.value)}
              hint="Maximum 2%"
            />
            <Input
              label="Cost per Side (bps)"
              type="number"
              min={0}
              step="any"
              value={costBps}
              onChange={(event) => setCostBps(event.target.value)}
            />
            <Input
              label="Max Position (%)"
              type="number"
              min={1}
              max={100}
              step="1"
              value={maxPositionPercent}
              onChange={(event) => setMaxPositionPercent(event.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" variant="primary" icon="flask" loading={loading}>
              Run Backtest
            </Button>
            <span className="text-2xs text-terminal-muted">Daily Bars Only</span>
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
            <Stat label="Profit Factor" value={profitFactor} hint="Gross Wins ÷ Gross Losses" />
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
