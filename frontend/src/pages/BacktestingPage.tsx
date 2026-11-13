import { useMemo, useState } from 'react';
import type { FormEvent } from 'react';
import { backtestService } from '../services/backtestService';
import type { BacktestRequest, BacktestResult, Market } from '../types/api';
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
  { value: 'india', label: 'Indian equities' },
  { value: 'global', label: 'International equities' },
  { value: 'crypto', label: 'Crypto spot' },
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
  const [days, setDays] = useState('1825');
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
      setError('Enter a symbol.');
      return;
    }
    if (!Number.isFinite(parsedDays) || parsedDays < 240 || parsedDays > 3650) {
      setError('History must be between 240 and 3650 days.');
      return;
    }
    if (!Number.isFinite(parsedCapital) || parsedCapital <= 0) {
      setError('Initial capital must be positive.');
      return;
    }
    if (!Number.isFinite(parsedRisk) || parsedRisk <= 0 || parsedRisk > 0.02) {
      setError('Risk per trade must be above 0 and at most 2%.');
      return;
    }
    if (!Number.isFinite(parsedCost) || parsedCost < 0) {
      setError('Cost per side must be zero or positive.');
      return;
    }
    if (!Number.isFinite(parsedMaxPosition) || parsedMaxPosition <= 0 || parsedMaxPosition > 1) {
      setError('Maximum position fraction must be above 0 and at most 100%.');
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
    };

    setLoading(true);
    try {
      setResult(await backtestService.run(payload));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Backtest failed');
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

  // Visualisation only: the underwater curve is derived from the equity points
  // that the backend already returned. It does not recalculate any strategy or
  // risk metric; the headline drawdown figure is backend `max_drawdown_pct`.
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
    <div>
      <PageHeader
        title="Backtesting"
        subtitle="Single-instrument research on the backend trend-breakout strategy. Daily candles only, costs included by the backend. Results are historical simulations, not forecasts."
      />

      <Card className="mb-4" title="Configuration" subtitle="Strategy parameters are enforced by the FastAPI backend.">
        <form onSubmit={runBacktest} className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
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
            <Input
              label="History (days)"
              type="number"
              min={240}
              max={3650}
              step={1}
              value={days}
              onChange={(event) => setDays(event.target.value)}
              hint="Backend range 240–3650"
            />
            <Input
              label="Initial capital"
              type="number"
              min={1}
              step="any"
              value={capital}
              onChange={(event) => setCapital(event.target.value)}
            />
            <Input
              label="Risk per trade (%)"
              type="number"
              min={0.01}
              max={2}
              step="0.01"
              value={riskPercent}
              onChange={(event) => setRiskPercent(event.target.value)}
              hint="Backend maximum 2%"
            />
            <Input
              label="Cost per side (bps)"
              type="number"
              min={0}
              step="any"
              value={costBps}
              onChange={(event) => setCostBps(event.target.value)}
            />
            <Input
              label="Max position (%)"
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
              Run backtest
            </Button>
            <p className="text-[11px] text-terminal-muted">
              The interval is fixed at daily bars; intraday requests are rejected by the backend.
            </p>
          </div>
        </form>

        {error ? <ErrorState className="mt-3" message={error} /> : null}
      </Card>

      {loading ? (
        <Card>
          <EmptyState
            title="Running the simulation…"
            description="The backend is fetching history and replaying the strategy. This can take a few seconds."
            icon="flask"
          />
        </Card>
      ) : result ? (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Net return"
              value={formatPercent(result.net_return_pct, 2, true)}
              tone={result.net_return_pct > 0 ? 'positive' : result.net_return_pct < 0 ? 'negative' : 'neutral'}
              hint={`Final equity ${formatNumber(result.final_equity, 2)}`}
            />
            <Stat label="Trades" value={String(result.trade_count)} hint={`Win rate ${formatPercent(result.win_rate_pct)}`} />
            <Stat label="Profit factor" value={profitFactor} hint="Gross wins ÷ gross losses" />
            <Stat
              label="Max drawdown"
              value={formatPercent(result.max_drawdown_pct)}
              tone="negative"
              hint="Reported by the backend"
            />
            <Stat
              label="Expectancy / trade"
              value={formatNumber(result.expectancy_per_trade, 2)}
              hint="Net of backend costs"
            />
            <Stat label="Sharpe (annualised)" value={formatNumber(result.sharpe_daily_annualized, 2)} hint="Daily returns basis" />
            <Stat label="Sortino (annualised)" value={formatNumber(result.sortino_daily_annualized, 2)} hint="Daily returns basis" />
            <Stat label="Costs per side" value={`${formatNumber(result.cost_bps_per_side, 2)} bps`} hint={result.data_adjusted ? 'Adjusted data' : 'Unadjusted data'} />
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">
            <Card
              className="xl:col-span-7"
              title="Equity curve"
              subtitle={`${result.strategy} · ${result.strategy_version} · ${result.source}`}
            >
              <TimeSeriesChart
                points={equityPoints}
                height={260}
                color="#2fd18a"
                baseline={result.initial_capital}
                valueFormatter={(value) => formatNumber(value, 2)}
                ariaLabel="Backtest equity curve"
              />
            </Card>
            <Card
              className="xl:col-span-5"
              title="Drawdown"
              subtitle="Underwater curve derived from the backend equity points for visualisation; the headline figure is backend-computed."
            >
              <TimeSeriesChart
                points={drawdownPoints}
                height={260}
                color="#ff6b6b"
                baseline={0}
                valueFormatter={(value) => `${formatNumber(value, 2)}%`}
                ariaLabel="Backtest drawdown curve"
              />
            </Card>
          </div>

          <Card
            title="Trades"
            subtitle={`${result.symbol} · ${result.market} · ${result.trade_count} completed round trips`}
          >
            <TradesTable trades={result.trades} />
          </Card>

          {result.limitations.length > 0 ? (
            <Card title="Model limitations">
              <ul className="list-disc space-y-1 pl-4 text-[11px] leading-relaxed text-terminal-muted">
                {result.limitations.map((limitation) => (
                  <li key={limitation}>{limitation}</li>
                ))}
              </ul>
            </Card>
          ) : null}
        </div>
      ) : (
        <Card>
          <EmptyState
            title="No backtest run yet"
            description="Configure a symbol and run the simulation. All metrics, trades and equity points are produced by the backend."
            icon="flask"
          />
        </Card>
      )}

      <Notice className="mt-4">
        Backtests are in-sample simulations with simplified fills and configurable costs. They do not
        model liquidity, taxes, corporate-action timing or slippage beyond the stated cost. Past
        performance does not indicate future results.
      </Notice>
    </div>
  );
}
