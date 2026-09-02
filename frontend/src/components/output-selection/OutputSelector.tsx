/**
 * TransformIQ — Output type multi-selector.
 *
 * Selectable cards for each supported output type. Cards behave as selection
 * controls (multi-select), NOT as navigation. Selected cards show a checkmark,
 * the output accent border, and a subtle background elevation.
 */
"use client";

import { Check } from "lucide-react";
import { OUTPUT_TYPES, type OutputTypeId } from "@/lib/outputTypes";
import { cn } from "@/lib/utils";

export type { OutputTypeId };

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

  const allSelected = selected.length === OUTPUT_TYPES.length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {selected.length > 0 && (
            <span className="text-xs font-medium text-foreground">
              {selected.length} output{selected.length !== 1 ? "s" : ""} selected
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs">
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange(OUTPUT_TYPES.map((o) => o.id))}
            className="text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            Select all
          </button>
          <span className="text-muted-foreground/40">·</span>
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange([])}
            className="text-muted-foreground transition-colors hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {OUTPUT_TYPES.map(({ id, shortLabel, description, icon: Icon, iconClass, accentClass, tintClass }) => {
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
                "group flex items-start gap-3 rounded-lg border p-3.5 text-left transition-all",
                active
                  ? cn(accentClass, tintClass)
                  : "border-border bg-surface-elevated hover:border-input hover:bg-muted/40",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              <span
                className={cn(
                  "mv-auto mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-md border transition-colors",
                  active
                    ? cn("border-transparent", tintClass)
                    : "border-border bg-background",
                )}
                aria-hidden="true"
              >
                <Icon className={cn("h-5 w-5", iconClass)} />
              </span>
              <span className="min-w-0 flex-1 space-y-0.5">
                <span className="block text-sm font-medium text-foreground">
                  {shortLabel}
                </span>
                <span className="block text-xs leading-relaxed text-muted-foreground">
                  {description}
                </span>
              </span>
              <span
                className={cn(
                  "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border transition-colors",
                  active
                    ? "border-transparent bg-primary text-primary-foreground"
                    : "border-input bg-background",
                )}
                aria-hidden="true"
              >
                {active && <Check className="h-3 w-3" strokeWidth={3} />}
              </span>
            </button>
          );
        })}
      </div>

      {allSelected && selected.length > 0 && (
        <p className="text-xs text-muted-foreground">
          All outputs selected.
        </p>
      )}
    </div>
  );
}
