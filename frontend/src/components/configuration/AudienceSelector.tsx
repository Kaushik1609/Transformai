/**
 * TransformIQ — Audience selector.
 *
 * Compact selectable pills for the target audience, plus an optional custom
 * audience value. Selection maps into the transformation configuration
 * (backend `target_audience` field).
 */
"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

export const AUDIENCE_OPTIONS = [
  "General",
  "Executives",
  "Technical",
  "Customers",
  "Investors",
  "Internal Team",
] as const;

interface AudienceSelectorProps {
  value: string | null;
  onChange: (audience: string | null) => void;
  disabled?: boolean;
}

export function AudienceSelector({
  value,
  onChange,
  disabled = false,
}: AudienceSelectorProps) {
  const [custom, setCustom] = useState("");
  const isCustom = value !== null && !AUDIENCE_OPTIONS.includes(value as (typeof AUDIENCE_OPTIONS)[number]);

  const selectPreset = (option: string) => {
    if (disabled) return;
    setCustom("");
    onChange(option);
  };

  const applyCustom = () => {
    if (disabled || !custom.trim()) return;
    onChange(custom.trim());
  };

  return (
    <div className="space-y-3">
      <div role="radiogroup" aria-label="Audience" className="flex flex-wrap gap-2">
        {AUDIENCE_OPTIONS.map((option) => {
          const active = value === option;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={active}
              disabled={disabled}
              onClick={() => selectPreset(option)}
              className={cn(
                "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
                active
                  ? "border-primary/60 bg-primary/10 font-medium text-primary"
                  : "border-border bg-surface-elevated text-muted-foreground hover:border-input hover:text-foreground",
                disabled && "cursor-not-allowed opacity-60",
              )}
            >
              {option}
            </button>
          );
        })}
        <button
          type="button"
          role="radio"
          aria-checked={isCustom}
          disabled={disabled}
          onClick={() => {
            if (!isCustom) setCustom(custom);
          }}
          className={cn(
            "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
            isCustom
              ? "border-primary/60 bg-primary/10 font-medium text-primary"
              : "border-border bg-surface-elevated text-muted-foreground hover:border-input hover:text-foreground",
            disabled && "cursor-not-allowed opacity-60",
          )}
        >
          Custom
        </button>
      </div>

      {isCustom && (
        <div className="flex items-center gap-2">
          <input
            aria-label="Custom audience"
            value={value ?? ""}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
            placeholder="Describe your audience…"
            className="input-base max-w-xs"
          />
        </div>
      )}

      {!isCustom && (
        <div className="flex items-center gap-2">
          <input
            aria-label="Custom audience"
            value={custom}
            disabled={disabled}
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") applyCustom();
            }}
            placeholder="Or type a custom audience…"
            className="input-base max-w-xs"
          />
          <button
            type="button"
            disabled={disabled || !custom.trim()}
            onClick={applyCustom}
            className="inline-flex items-center rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}
