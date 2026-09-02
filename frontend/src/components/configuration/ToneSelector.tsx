/**
 * TransformIQ — Tone selector.
 *
 * Compact selectable pills for the tone of the transformation. A single primary
 * tone maps into the transformation configuration (backend `tone` field).
 */
"use client";

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
  return (
    <div role="radiogroup" aria-label="Tone" className="flex flex-wrap gap-2">
      {TONE_OPTIONS.map((tone) => {
        const active = value === tone;
        return (
          <button
            key={tone}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={disabled}
            onClick={() => onChange(tone)}
            className={cn(
              "rounded-full border px-3.5 py-1.5 text-sm transition-colors",
              active
                ? "border-primary/60 bg-primary/10 font-medium text-primary"
                : "border-border bg-surface-elevated text-muted-foreground hover:border-input hover:text-foreground",
              disabled && "cursor-not-allowed opacity-60",
            )}
          >
            {tone}
          </button>
        );
      })}
    </div>
  );
}
