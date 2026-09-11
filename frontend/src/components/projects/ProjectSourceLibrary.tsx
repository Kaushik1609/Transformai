/**
 * TransformIQ — Project source library (UI-7).
 *
 * Lists a project's sources with the backend-recorded processing state and
 * the security signals derived ONLY from real source metadata (malware scan
 * result, PII scan result). A scan that has no recorded result is shown as
 * UNAVAILABLE, never as a clean pass, and raw PII contents are never exposed.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import type { SourceResponse } from "@/lib/api";
import { sourcesApi, errorMessage } from "@/lib/api";
import { timeAgo, formatFileSize } from "@/lib/outputTypes";
import { StatusBadge, EmptyState, ErrorState, LoadingSpinner } from "@/components/common";
import { Database, FileUp, ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import { cn } from "@/lib/utils";

export type SourceStatusLabel =
  | "Ready"
  | "Processing"
  | "Failed"
  | "Unavailable";

export type SecuritySignal =
  | "CLEAN"
  | "BLOCKED"
  | "DETECTED"
  | "NOT_DETECTED"
  | "UNAVAILABLE";

export function sourceStatusLabel(status: string | undefined): SourceStatusLabel {
  switch (status) {
    case "ready":
      return "Ready";
    case "processing":
    case "uploaded":
      return "Processing";
    case "failed":
      return "Failed";
    default:
      return "Unavailable";
  }
}

function sourceStatusVariant(status: string | undefined) {
  switch (status) {
    case "ready":
      return "success";
    case "processing":
    case "uploaded":
      return "info";
    case "failed":
      return "error";
    default:
      return "muted";
  }
}

function signalVariant(signal: SecuritySignal) {
  switch (signal) {
    case "CLEAN":
    case "NOT_DETECTED":
      return "success";
    case "DETECTED":
    case "BLOCKED":
      return "warning";
    default:
      return "muted";
  }
}

/**
 * Map source metadata to bounded, honest security signals. Only the scan
 * status is surfaced — never the raw PII values (counts, email strings, …).
 */
export function sourceSecuritySignals(
  source: SourceResponse,
): { malware: SecuritySignal; pii: SecuritySignal } {
  const meta = (source.source_metadata ?? {}) as Record<string, unknown>;
  const malware = (meta.malware_scan ?? {}) as { status?: unknown } | undefined;
  const pii = (meta.pii_scan ?? {}) as { detected?: unknown } | undefined;

  let malwareSignal: SecuritySignal = "UNAVAILABLE";
  if (malware && typeof malware.status === "string") {
    if (malware.status === "clean") malwareSignal = "CLEAN";
    else if (malware.status === "infected") malwareSignal = "BLOCKED";
  }

  let piiSignal: SecuritySignal = "UNAVAILABLE";
  if (pii && typeof pii.detected === "boolean") {
    piiSignal = pii.detected ? "DETECTED" : "NOT_DETECTED";
  }

  return { malware: malwareSignal, pii: piiSignal };
}

interface ProjectSourceLibraryProps {
  projectId: string;
  selectedSourceId?: string | null;
  onTransformSource?: (sourceId: string) => void;
}

export function ProjectSourceLibrary({
  projectId,
  selectedSourceId,
  onTransformSource,
}: ProjectSourceLibraryProps) {
  const [sources, setSources] = useState<SourceResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSources = useCallback(async () => {
    setError(null);
    try {
      const res = await sourcesApi.list(projectId);
      setSources(res.data);
    } catch (err) {
      setError(errorMessage(err, "Failed to load sources."));
    }
  }, [projectId]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  return (
    <section
      className="rounded-lg border border-border bg-surface-elevated p-4"
      aria-label="Source library"
    >
      <div className="mb-3 flex items-center justify-between gap-2 border-b border-border/60 pb-2">
        <h2 className="label-mono-sm flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          <Database className="h-3.5 w-3.5" aria-hidden="true" />
          Source library
        </h2>
        {sources && sources.length > 0 && (
          <span className="text-[10px] text-muted-foreground">
            {sources.length} source{sources.length !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {error ? (
        <ErrorState message={error} onRetry={() => void loadSources()} />
      ) : sources === null ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <LoadingSpinner size="sm" label="Loading sources…" />
          Loading sources…
        </div>
      ) : sources.length === 0 ? (
        <EmptyState
          title="No sources yet"
          description="Add a source in the transformation workspace to begin."
        />
      ) : (
        <ul className="space-y-2">
          {sources.map((source) => {
            const signals = sourceSecuritySignals(source);
            const ready = source.status === "ready";
            const selected = source.id === selectedSourceId;
            return (
              <li
                key={source.id}
                className={cn(
                  "rounded-md border border-border/60 bg-muted/20 p-3",
                  selected && "border-primary/50 bg-muted/40",
                )}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <FileUp className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                      <p className="truncate text-sm font-medium text-foreground">
                        {source.original_filename || "Untitled source"}
                      </p>
                      {selected && (
                        <StatusBadge variant="info">Selected</StatusBadge>
                      )}
                    </div>
                    <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[11px] text-muted-foreground">
                      <dd className="capitalize">
                        {source.source_type} ·{" "}
                        {formatFileSize(source.file_size)}
                      </dd>
                      <dd>Uploaded {timeAgo(source.created_at)}</dd>
                    </dl>
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <StatusBadge variant={sourceStatusVariant(source.status)}>
                      {sourceStatusLabel(source.status)}
                    </StatusBadge>
                    <div className="flex items-center gap-1">
                      <StatusBadge variant={signalVariant(signals.malware)}>
                        <ShieldCheck className="mr-1 h-3 w-3" aria-hidden="true" />
                        Malware {signals.malware}
                      </StatusBadge>
                      <StatusBadge variant={signalVariant(signals.pii)}>
                        {signals.pii === "DETECTED" ? (
                          <ShieldAlert className="mr-1 h-3 w-3" aria-hidden="true" />
                        ) : (
                          <ShieldQuestion className="mr-1 h-3 w-3" aria-hidden="true" />
                        )}
                        PII {signals.pii}
                      </StatusBadge>
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => onTransformSource?.(source.id)}
                  disabled={!ready || !onTransformSource}
                  title={
                    ready
                      ? "Transform with this source"
                      : "This source is not ready to transform"
                  }
                  aria-pressed={selected}
                  className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Transform with this source
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}