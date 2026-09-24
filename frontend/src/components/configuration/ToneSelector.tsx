/**
 * TransformIQ — Tone selector.
 *
 * Compact collapsed dropdown selector for the tone of the transformation.
 * A single primary tone maps into the transformation configuration (backend `tone` field).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export const TONE_OPTIONS = [
  "Professional",
  "Conversational",
  "Executive",
  "Technical",
  "Persuasive",
  "Concise",
] as const;

export type Tone = (typeof TONE_OPTIONS)[number];

interface ToneSelectorProps {
  value: Tone | null;
  onChange: (tone: Tone) => void;
  disabled?: boolean;
}

export function ToneSelector({ value, onChange, disabled = false }: ToneSelectorProps) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const selected = value ?? "Professional";

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

  return (
    <div ref={containerRef} className="relative w-full">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Select tone"
        className={cn(
          "flex w-full items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated px-3 py-2 text-sm text-foreground shadow-sm transition-colors hover:border-input focus:outline-none focus:ring-1 focus:ring-primary",
          disabled && "cursor-not-allowed opacity-60",
        )}
      >
        <div className="flex items-center gap-2 truncate">
          <span className="font-medium text-foreground">{selected}</span>
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
          aria-label="Tone options"
          className="absolute left-0 top-full z-50 mt-1.5 w-full min-w-[200px] overflow-hidden rounded-lg border border-border bg-popover p-1 text-popover-foreground shadow-lg animate-in fade-in-0 zoom-in-95"
        >
          {TONE_OPTIONS.map((tone) => {
            const active = selected === tone;
            return (
              <button
                key={tone}
                type="button"
                role="option"
                aria-selected={active}
                disabled={disabled}
                onClick={() => {
                  onChange(tone);
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                  active
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-foreground hover:bg-muted",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <span>{tone}</span>
                {active && <Check className="h-4 w-4 text-primary" aria-hidden="true" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
