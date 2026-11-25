import type { StrategySignal } from "../../types/api";
import { Card } from "../common/Card";
import { Badge } from "../common/Badge";
import { SignalBadge } from "./SignalBadge";
import { ConditionList } from "./ConditionList";
import { Select } from "../common/Field";
import type { DirectionMode } from "../../types/api";
import { useState } from "react";

export function SignalCard({
  signal,
  directionMode,
  onDirectionModeChange,
  isStale,
}: {
  signal: StrategySignal;
  directionMode?: DirectionMode;
  onDirectionModeChange?: (mode: DirectionMode) => void;
  isStale?: boolean;
}) {
  const [localDirectionMode, setLocalDirectionMode] = useState<DirectionMode>(signal.direction_mode ?? "long_only");
  const selectedDirection = directionMode ?? localDirectionMode;
  const stale = isStale ?? signal.state === "STALE_DATA";
  return (
    <Card
      title={signal.strategy}
      actions={
        <div className="flex items-center gap-1">
          {signal.direction ? <Badge>{signal.direction}</Badge> : null}
          {!stale ? <SignalBadge state={signal.state} /> : null}
        </div>
      }
    >
      <div>
        <div className="mb-2 flex flex-wrap items-end justify-between gap-2">
          <Select
            label="Strategy Direction"
            wrapperClassName="w-40"
            value={selectedDirection}
            onChange={(event) => {
              const nextDirection = event.target.value as DirectionMode;
              if (onDirectionModeChange) onDirectionModeChange(nextDirection);
              else setLocalDirectionMode(nextDirection);
            }}
            options={[
              { value: "long_only", label: "Long Only" },
              { value: "short_only", label: "Short Only" },
              { value: "long_short", label: "Long + Short" },
            ]}
          />
          {stale ? <Badge tone="warning">Stale</Badge> : null}
        </div>
        <p className="mb-1 text-2xs text-terminal-muted">Manual Signal · No Order Execution</p>
        <ConditionList conditions={signal.conditions} />
      </div>
    </Card>
  );
}
