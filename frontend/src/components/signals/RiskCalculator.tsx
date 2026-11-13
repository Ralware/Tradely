import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { riskService } from '../../services/riskService';
import type { RiskResult } from '../../types/api';
import { formatNumber } from '../../utils/format';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { Field, Input } from '../common/Field';
import { ErrorState, Notice } from '../common/States';
import { KeyValue } from '../common/Stat';

interface RiskCalculatorProps {
  entry: number | null;
  stop: number | null;
  currency?: string | null;
}

export function RiskCalculator({ entry, stop, currency }: RiskCalculatorProps) {
  const [capital, setCapital] = useState('100000');
  const [riskPercent, setRiskPercent] = useState('0.5');
  const [entryPrice, setEntryPrice] = useState(entry === null ? '' : String(entry));
  const [stopPrice, setStopPrice] = useState(stop === null ? '' : String(stop));
  const [lotSize, setLotSize] = useState('1');
  const [result, setResult] = useState<RiskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (entry !== null) {
      setEntryPrice(String(entry));
    }
    if (stop !== null) {
      setStopPrice(String(stop));
    }
  }, [entry, stop]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    const payload = {
      capital: Number(capital),
      risk_fraction: Number(riskPercent) / 100,
      entry: Number(entryPrice),
      stop: Number(stopPrice),
      lot_size: Number(lotSize),
      max_position_fraction: 1,
    };

    if (
      !Number.isFinite(payload.capital) ||
      !Number.isFinite(payload.risk_fraction) ||
      !Number.isFinite(payload.entry) ||
      !Number.isFinite(payload.stop) ||
      !Number.isFinite(payload.lot_size)
    ) {
      setError('Enter valid numeric values.');
      return;
    }

    setLoading(true);
    try {
      setResult(await riskService.calculate(payload));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Position sizing failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card
      title="Position sizing"
      subtitle="ATR/stop-based risk budget calculated by the FastAPI backend."
    >
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Account capital">
            <Input
              type="number"
              min={1}
              step="any"
              value={capital}
              onChange={(event) => setCapital(event.target.value)}
            />
          </Field>
          <Field label="Risk per trade (%)" hint="Backend maximum is 2%.">
            <Input
              type="number"
              min={0.01}
              max={2}
              step="0.01"
              value={riskPercent}
              onChange={(event) => setRiskPercent(event.target.value)}
            />
          </Field>
          <Field label="Entry price">
            <Input
              type="number"
              min={0}
              step="any"
              value={entryPrice}
              onChange={(event) => setEntryPrice(event.target.value)}
            />
          </Field>
          <Field label="Stop price">
            <Input
              type="number"
              min={0}
              step="any"
              value={stopPrice}
              onChange={(event) => setStopPrice(event.target.value)}
            />
          </Field>
          <Field label="Lot size">
            <Input
              type="number"
              min={1}
              step={1}
              value={lotSize}
              onChange={(event) => setLotSize(event.target.value)}
            />
          </Field>
        </div>

        <Button type="submit" variant="primary" loading={loading}>
          Calculate position size
        </Button>
      </form>

      {error ? <ErrorState className="mt-3" message={error} /> : null}

      {result ? (
        <dl className="mt-3 divide-y divide-terminal-borderSoft rounded-lg border border-terminal-borderSoft bg-terminal-panelAlt px-3 py-1">
          <KeyValue label="Risk budget" value={formatNumber(result.risk_budget, 2)} />
          <KeyValue label="Risk per unit" value={formatNumber(result.risk_per_unit, 2)} />
          <KeyValue label="Quantity" value={formatNumber(result.quantity, 0)} />
          <KeyValue
            label="Position value"
            value={`${formatNumber(result.position_value, 2)}${currency ? ` ${currency}` : ''}`}
          />
          <KeyValue label="Planned loss" value={formatNumber(result.planned_loss, 2)} />
          <KeyValue
            label="Limited by"
            value={result.capital_limited ? 'Position capital' : 'Risk budget'}
          />
        </dl>
      ) : null}

      <Notice className="mt-3">
        Position sizing excludes charges, spread, slippage, partial fills and gap risk. A stop order
        does not guarantee a fill at the stop price.
      </Notice>
    </Card>
  );
}
