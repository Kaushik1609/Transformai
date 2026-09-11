/**
 * TransformIQ — Stitch-style "Output Packages" selection grid.
 *
 * Seven selectable output packages (Summary, LinkedIn, X Thread, Advisory,
 * Infographic, Presentation, Video Package). Cards behave as selection
 * controls (role=checkbox), NOT as navigation. A "Select All / Reset" toolbar
 * mirrors the reference workspace's package selection header.
 */
"use client";

import { Check, Sparkles, Package } from "lucide-react";
import { OUTPUT_TYPES, type OutputTypeId } from "@/lib/outputTypes";
import { cn } from "@/lib/utils";

const FORMAT_METADATA: Record<
  OutputTypeId,
  { genre: string; schema: string }
> = {
  summary: {
    genre: "Document",
    schema: "Markdown / PDF",
  },
  linkedin: {
    genre: "Social",
    schema: "Social Copy",
  },
  x: {
    genre: "Thread",
    schema: "Threaded Text",
  },
  advisory: {
    genre: "Memo",
    schema: "DOCX / HTML",
  },
  infographic: {
    genre: "Visual",
    schema: "Visual JSON / SVG",
  },
  presentation: {
    genre: "Slides",
    schema: "PPTX Schema",
  },
  video: {
    genre: "Video Spec",
    schema: "Audio/Visual Script",
  },
};

interface OutputPackageGridProps {
  selected: OutputTypeId[];
  onChange: (next: OutputTypeId[]) => void;
  disabled?: boolean;
}

export function OutputPackageGrid({
  selected,
  onChange,
  disabled = false,
}: OutputPackageGridProps) {
  const toggle = (id: OutputTypeId) => {
    if (disabled) return;
    onChange(
      selected.includes(id)
        ? selected.filter((s) => s !== id)
        : [...selected, id],
    );
  };

  const allSelected = selected.length === OUTPUT_TYPES.length;

  const applyCSuitePreset = () => {
    if (disabled) return;
    onChange(["summary", "advisory", "presentation"]);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Package className="h-5 w-5 text-primary" />
            <span className="label-mono-xs uppercase tracking-wider text-muted-foreground">
              Output Packages
            </span>
          </div>
          <h2 className="headline-lg font-semibold tracking-tight text-foreground">
            Choose Your Outputs
          </h2>
          <p className="text-xs text-muted-foreground">
            Select target communication artifacts. KaryaSetu AI simultaneously maps grounded
            citations across each output.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span aria-live="polite" className="label-mono-sm font-medium text-foreground">
            {selected.length} format{selected.length !== 1 ? "s" : ""} selected
          </span>
          <span className="text-muted-foreground/40">·</span>
          <button
            type="button"
            disabled={disabled || allSelected}
            onClick={() => onChange(OUTPUT_TYPES.map((o) => o.id))}
            className="rounded bg-surface-container px-2.5 py-1 label-mono-sm text-foreground transition-colors hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
          >
            Select All
          </button>
          <button
            type="button"
            disabled={disabled || selected.length === 0}
            onClick={() => onChange([])}
            className="rounded bg-surface-container px-2.5 py-1 label-mono-sm text-muted-foreground transition-colors hover:bg-surface-container-high hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            Reset
          </button>
          <button
            type="button"
            disabled={disabled}
            onClick={applyCSuitePreset}
            className="inline-flex items-center gap-1 rounded bg-secondary/15 px-3 py-1 label-mono-sm text-secondary-fixed-dim transition-colors hover:bg-secondary/25"
          >
            <Sparkles className="h-3 w-3" />
            <span>Preset: C-Suite</span>
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {OUTPUT_TYPES.map(
          ({
            id,
            shortLabel,
            description,
            icon: Icon,
            iconClass,
          }) => {
            const active = selected.includes(id);
            const meta = FORMAT_METADATA[id];
            return (
              <button
                key={id}
                type="button"
                role="checkbox"
                aria-checked={active}
                disabled={disabled}
                onClick={() => toggle(id)}
                className={cn(
                  "group flex flex-col justify-between rounded-xl border p-4 text-left transition-all",
                  active
                    ? "border-primary/60 bg-surface-container-high ring-1 ring-primary shadow-[0_0_12px_rgba(37,99,235,0.2)]"
                    : "border-border-subtle bg-surface-container-low hover:border-border-default hover:bg-surface-container",
                  disabled && "cursor-not-allowed opacity-60",
                )}
              >
                <div className="flex flex-col gap-3">
                  <div className="flex items-start justify-between">
                    <span
                      className={cn(
                        "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition-colors",
                        active
                          ? "border-transparent bg-primary text-primary-foreground shadow-sm"
                          : "border-border-subtle bg-surface-container text-muted-foreground group-hover:text-foreground",
                      )}
                      aria-hidden="true"
                    >
                      <Icon className={cn("h-4 w-4", active ? "text-primary-foreground" : iconClass)} />
                    </span>
                    <span
                      className={cn(
                        "flex h-5 w-5 shrink-0 items-center justify-center rounded border transition-colors",
                        active
                          ? "border-transparent bg-primary text-primary-foreground"
                          : "border-border-default bg-surface-container-highest text-transparent",
                      )}
                      aria-hidden="true"
                    >
                      {active && <Check className="h-3.5 w-3.5 stroke-[3]" />}
                    </span>
                  </div>
                  <div className="flex flex-col">
                    <div className="flex items-center gap-2">
                      <span className="headline-sm font-semibold text-foreground">
                        {shortLabel}
                      </span>
                      <span className="label-mono-sm rounded bg-surface-container-lowest px-1.5 py-0.5 text-[10px] text-muted-foreground uppercase">
                        {meta.genre}
                      </span>
                    </div>
                    <p className="caption mt-1.5 line-clamp-2 leading-relaxed text-muted-foreground">
                      {description}
                    </p>
                  </div>
                </div>

                <div className="mt-4 flex items-center justify-end border-t border-outline-variant/30 pt-3 label-mono-sm text-outline">
                  <span className="rounded bg-surface-container-highest px-1.5 py-0.5 text-[10px] text-foreground">
                    {meta.schema}
                  </span>
                </div>
              </button>
            );
          },
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 pt-1 text-xs">
        <p className="caption text-muted-foreground">
          {allSelected && selected.length > 0
            ? "All 7 transformation packages selected for simultaneous dispatch."
            : "Select deliverables to orchestrate in parallel with deterministic line-by-line provenance."}
        </p>
      </div>
    </div>
  );
}