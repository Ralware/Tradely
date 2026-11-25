import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { riskService } from "../../services/riskService";
import type { PositionDirection, RiskResult } from "../../types/api";
import { formatNumber } from "../../utils/format";
import { Button } from "../common/Button";
import { Card } from "../common/Card";
import { Input, Select } from "../common/Field";
import { ErrorState, Notice } from "../common/States";
import { KeyValue } from "../common/Stat";

interface RiskCalculatorProps {
  entry: number | null;
  stop: number | null;
  direction?: PositionDirection;
  currency?: string | null;
}

export function RiskCalculator({
  entry,
  stop,
  direction = "LONG",
  currency,
}: RiskCalculatorProps) {
  const [capital, setCapital] = useState("100000");
  const [riskPercent, setRiskPercent] = useState("0.5");
  const [entryPrice, setEntryPrice] = useState(
    entry === null ? "" : String(entry),
  );
  const [stopPrice, setStopPrice] = useState(stop === null ? "" : String(stop));
  const [positionDirection, setPositionDirection] = useState(direction);
  const [lotSize, setLotSize] = useState("1");
  const [result, setResult] = useState<RiskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorKind, setErrorKind] = useState<"validation" | "request">(
    "validation",
  );
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (entry !== null) {
      setEntryPrice(String(entry));
    }
    setStopPrice(stop === null ? "" : String(stop));
    setPositionDirection(direction);
  }, [entry, stop, direction]);

  function fail(message: string) {
    setErrorKind("validation");
    setError(message);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setResult(null);

    const payload = {
      capital: Number(capital),
      risk_fraction: Number(riskPercent) / 100,
      entry: Number(entryPrice),
      stop: Number(stopPrice),
      direction: positionDirection,
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
      fail("Enter valid numeric values.");
      return;
    }
    if (payload.capital <= 0) {
      fail("Account capital must be above zero.");
      return;
    }
    if (payload.risk_fraction <= 0 || payload.risk_fraction > 0.02) {
      fail("Risk per trade must be above 0% and at most 2%.");
      return;
    }
    if (payload.entry <= 0) {
      fail("Entry price must be above zero.");
      return;
    }
    if (payload.stop <= 0) {
      fail("Stop price must be above zero.");
      return;
    }
    if (
      (payload.direction === "LONG" && payload.stop >= payload.entry) ||
      (payload.direction === "SHORT" && payload.stop <= payload.entry)
    ) {
      fail(
        payload.direction === "LONG"
          ? "Stop price must be below the entry price."
          : "Stop price must be above the entry price.",
      );
      return;
    }
    if (payload.lot_size < 1) {
      fail("Lot size must be at least 1.");
      return;
    }

    setLoading(true);
    try {
      setResult(await riskService.calculate(payload));
    } catch (caught) {
      setErrorKind("request");
      setError(
        caught instanceof Error ? caught.message : "Position Sizing Failed",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <Card title="Position Sizing" subtitle="Backend Risk Calculation">
      <form onSubmit={submit} className="space-y-2">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <Select
            label="Direction"
            value={positionDirection}
            onChange={(event) =>
              setPositionDirection(event.target.value as PositionDirection)
            }
            options={[
              { value: "LONG", label: "Long" },
              { value: "SHORT", label: "Short" },
            ]}
          />
          <Input
            label="Account Capital"
            type="number"
            min={1}
            step="any"
            value={capital}
            onChange={(event) => setCapital(event.target.value)}
          />
          <Input
            label="Risk per Trade (%)"
            hint="Maximum 2%"
            type="number"
            min={0.01}
            max={2}
            step="0.01"
            value={riskPercent}
            onChange={(event) => setRiskPercent(event.target.value)}
          />
          <Input
            label="Entry Price"
            type="number"
            min={0}
            step="any"
            value={entryPrice}
            onChange={(event) => setEntryPrice(event.target.value)}
          />
          <Input
            label="Stop Price"
            type="number"
            min={0}
            step="any"
            value={stopPrice}
            onChange={(event) => setStopPrice(event.target.value)}
          />
          <Input
            label="Lot Size"
            type="number"
            min={1}
            step={1}
            value={lotSize}
            onChange={(event) => setLotSize(event.target.value)}
          />
        </div>

        <Button type="submit" variant="primary" loading={loading}>
          Calculate Position Size
        </Button>
      </form>

      {error ? (
        <ErrorState
          className="mt-2"
          title={errorKind === "validation" ? "Check Inputs" : "Request Failed"}
          message={error}
        />
      ) : null}

      {result ? (
        <dl className="mt-2 divide-y divide-terminal-borderSoft border-y border-terminal-borderSoft">
          <KeyValue
            label="Direction"
            value={result.direction === "SHORT" ? "Short" : "Long"}
          />
          <KeyValue
            label="Risk Budget"
            value={formatNumber(result.risk_budget, 2)}
          />
          <KeyValue
            label="Risk per Unit"
            value={formatNumber(result.risk_per_unit, 2)}
          />
          <KeyValue label="Quantity" value={formatNumber(result.quantity, 0)} />
          <KeyValue
            label="Position Value"
            value={`${formatNumber(result.position_value, 2)}${currency ? ` ${currency}` : ""}`}
          />
          <KeyValue
            label="Planned Loss"
            value={formatNumber(result.planned_loss, 2)}
          />
          <KeyValue
            label="Limited By"
            value={result.capital_limited ? "Position Capital" : "Risk Budget"}
          />
        </dl>
      ) : null}

      {result && result.quantity <= 0 ? (
        <Notice tone="warning" className="mt-2">
          Whole-unit quantity rounds down to zero because{" "}
          {result.capital_limited
            ? "the account capital cannot fund one lot at this entry price."
            : "the risk budget cannot fund one lot at this stop distance."}{" "}
          Increase capital or risk per trade.
        </Notice>
      ) : null}

      <Notice className="mt-2">
        Excludes charges, spread, slippage, partial fills and gap risk.
      </Notice>
    </Card>
  );
}
