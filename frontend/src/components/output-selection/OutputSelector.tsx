/**
 * TransformIQ — Output type selector.
 *
 * Selectable cards for each supported output type. Selection is validated
 * against the backend's supported output types.
 */
"use client";

import { OUTPUT_TYPES, type OutputTypeId } from "@/lib/outputTypes";
import { cn } from "@/lib/utils";

interface OutputSelectorProps {
  selected: OutputTypeId[];
  onChange: (next: OutputTypeId[]) => void;
  disabled?: boolean;
}

export function OutputSelector({
  selected,
  onChange,
  disabled = false,
}: OutputSelectorProps) {
  const toggle = (id: OutputTypeId) => {
    if (disabled) return;
    onChange(
      selected.includes(id)
        ? selected.filter((s) => s !== id)
        : [...selected, id],
    );
  };

  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {OUTPUT_TYPES.map(({ id, label, description }) => {
        const active = selected.includes(id);
        return (
          <button
            key={id}
            type="button"
            role="checkbox"
            aria-checked={active}
            disabled={disabled}
            onClick={() => toggle(id)}
            className={cn(
              "flex items-start gap-3 rounded-md border p-3 text-left transition-colors",
              active
                ? "border-primary/50 bg-primary/5"
                : "border-border bg-background hover:bg-muted/40",
              disabled && "cursor-not-allowed opacity-60",
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border",
                active
                  ? "border-primary bg-primary text-primary-foreground"
                  : "border-muted-foreground/50",
              )}
            >
              {active && (
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  className="h-3 w-3"
                >
                  <path
                    fillRule="evenodd"
                    d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 0 1 1.05-.143Z"
                    clipRule="evenodd"
                  />
                </svg>
              )}
            </span>
            <span className="space-y-0.5">
              <span className="block text-sm font-medium text-foreground">
                {label}
              </span>
              <span className="block text-xs text-muted-foreground">
                {description}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}