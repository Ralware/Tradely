import type { SignalCondition } from "../../types/api";
import { cn } from "../../utils/format";
import { Icon } from "../common/Icon";

export function ConditionList({
  conditions,
}: {
  conditions: SignalCondition[];
}) {
  if (conditions.length === 0) {
    return (
      <p className="text-xs text-terminal-muted">No Conditions Evaluated</p>
    );
  }

  return (
    <ul className="divide-y divide-terminal-borderSoft">
      {conditions.map((condition) => (
        <li key={condition.name} className="flex items-center gap-2 py-1">
          <span
            className={cn(
              "flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded border",
              condition.passed
                ? "border-[#1f4d43] bg-terminal-panelAlt text-terminal-green"
                : "border-terminal-border bg-terminal-panelAlt text-terminal-muted",
            )}
            aria-label={condition.passed ? "Passed" : "Not Passed"}
          >
            {condition.passed ? (
              <Icon name="check" size={10} />
            ) : (
              <Icon name="close" size={9} />
            )}
          </span>
          <div className="min-w-0">
            <p
              className={cn(
                "text-xs font-medium",
                condition.passed ? "text-terminal-text" : "text-terminal-muted",
              )}
            >
              {condition.name}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
