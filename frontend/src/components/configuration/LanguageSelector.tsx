/**
 * TransformIQ — Output language selector.
 *
 * Compact collapsed dropdown selector for the language the outputs should be written in,
 * plus an optional custom language value. Maps into the transformation
 * configuration (backend `language` field).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export const LANGUAGE_OPTIONS = [
  "English",
  "Hindi",
  "Spanish",
  "French",
  "German",
  "Portuguese",
  "Chinese",
  "Arabic",
  "Japanese",
  "Korean",
] as const;

interface LanguageSelectorProps {
  value: string | null;
  onChange: (language: string | null) => void;
  disabled?: boolean;
}

export function LanguageSelector({
  value,
  onChange,
  disabled = false,
}: LanguageSelectorProps) {
  const [open, setOpen] = useState(false);
  const [customInput, setCustomInput] = useState("");
  const [showCustomField, setShowCustomField] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const isPreset =
    value !== null &&
    LANGUAGE_OPTIONS.includes(value as (typeof LANGUAGE_OPTIONS)[number]);
  const isCustom = value !== null && !isPreset;
  const displayLabel = value ?? "English";

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
      }
    };
    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [open]);

  const selectPreset = (option: string) => {
    if (disabled) return;
    setShowCustomField(false);
    onChange(option);
    setOpen(false);
  };

  const applyCustom = () => {
    if (disabled || !customInput.trim()) return;
    onChange(customInput.trim());
    setOpen(false);
  };

  return (
    <div ref={containerRef} className="relative w-full">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Select language"
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground shadow-sm transition-colors hover:border-input focus:outline-none focus:ring-1 focus:ring-primary",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <div className="flex items-center gap-2 truncate">
          <span className="font-medium text-foreground">{displayLabel}</span>
          {isCustom && (
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
              Custom
            </span>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-150",
            open && "rotate-180 text-foreground",
          )}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Language options"
          className="absolute left-0 top-full z-50 mt-1.5 max-h-72 w-full min-w-[240px] overflow-y-auto rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg animate-in fade-in-0 zoom-in-95"
        >
          {LANGUAGE_OPTIONS.map((option) => {
            const active = isPreset && value === option;
            return (
              <button
                key={option}
                type="button"
                role="option"
                aria-selected={active}
                disabled={disabled}
                onClick={() => selectPreset(option)}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-foreground hover:bg-muted",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <span>{option}</span>
                {active && <Check className="h-4 w-4 text-primary" aria-hidden="true" />}
              </button>
            );
          })}

          <div className="my-1 border-t border-border" />

          {/* Custom option */}
          <div className="p-1">
            {!showCustomField && !isCustom ? (
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  setShowCustomField(true);
                  setCustomInput(isCustom ? (value ?? "") : "");
                }}
                className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
              >
                <span>Custom…</span>
              </button>
            ) : (
              <div className="space-y-2 p-1.5">
                <input
                  aria-label="Custom language"
                  value={customInput || (isCustom ? (value ?? "") : "")}
                  disabled={disabled}
                  onChange={(e) => setCustomInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      applyCustom();
                    }
                  }}
                  placeholder="e.g. Marathi, Tamil…"
                  className="input-base w-full text-xs"
                  autoFocus
                />
                <div className="flex items-center justify-end gap-1.5">
                  <button
                    type="button"
                    onClick={() => setShowCustomField(false)}
                    className="rounded px-2 py-1 text-xs text-muted-foreground hover:text-foreground"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    disabled={disabled || !customInput.trim()}
                    onClick={applyCustom}
                    className="rounded bg-primary px-2.5 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                  >
                    Apply
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}