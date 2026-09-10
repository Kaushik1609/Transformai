/**
 * TransformIQ — Artifact inspector (UI-9).
 *
 * A consolidated, single-artifact inspection panel shown in the results
 * workspace for the active output tab. It composes the existing
 * backend-driven readouts — per-type previews, export/download actions,
 * artifact integrity, verification and fact verification — around the real
 * OutputResponse record:
 *
 *   LEDGER (header) → METADATA → ACTIONS → PREVIEW → INTEGRITY → VERIFICATION
 *
 * Only real output fields are rendered. Nothing is estimated client-side:
 * no trust percentages, no fabricated file URLs, no invented content streams,
 * and binary outputs that have no downloadable artifact say so honestly.
 */
"use client";

import type { OutputResponse } from "@/lib/api";
import {
  outputStatusVariant,
  outputTypeInfo,
  outputTypeLabel,
  outputFailureDetails,
  formatDateTime,
  type OutputTypeId,
} from "@/lib/outputTypes";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/common";
import { DownloadButton, CopyButton, ExportButton } from "@/components/export";
import { artifactOptions } from "@/components/export/DownloadButton";
import {
  VerificationPanel,
  FactVerificationPanel,
  ArtifactIntegrity,
} from "@/components/verification";
import {
  Box,
  CalendarClock,
  Eye,
  Type,
} from "lucide-react";
import { FailureDetails, OutputContent } from "./ResultsPanel";

const BINARY_OUTPUT_TYPES = new Set(["infographic", "presentation", "video"]);

function shortId(id: string): string {
  return id.length > 16 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
}

interface ArtifactInspectorProps {
  output: OutputResponse;
}

export function ArtifactInspector({ output }: ArtifactInspectorProps) {
  const info = outputTypeInfo(output.output_type as OutputTypeId);
  const Icon = info.icon;
  const failed = output.status === "failed";
  const generating = output.status === "generating";
  const isBinary = BINARY_OUTPUT_TYPES.has(output.output_type);
  const hasArtifact = artifactOptions(output).length > 0;
  const failure = outputFailureDetails(output);

  return (
    <article
      aria-label={`${outputTypeLabel(output.output_type)} artifact`}
      className="space-y-3"
    >
      {/* LEDGER — header */}
      <header className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-elevated px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className={cn(
              "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
              info.tintClass,
            )}
          >
            <Icon className={cn("h-4 w-4", info.iconClass)} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h4 className="truncate text-sm font-semibold text-foreground">
              {outputTypeLabel(output.output_type)}
            </h4>
            <p className="truncate font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
              {output.output_type} · {shortId(output.id)}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <ArtifactIntegrity output={output} compact />
          <StatusBadge variant={outputStatusVariant(output.status)}>
            {output.status}
          </StatusBadge>
        </div>
      </header>

      {/* METADATA — real output record */}
      <dl className="grid grid-cols-2 gap-3 rounded-lg border border-border bg-surface-elevated px-4 py-3 text-xs sm:grid-cols-3">
        <Meta
          icon={<CalendarClock className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Generated"
          value={formatDateTime(output.created_at)}
        />
        <Meta
          icon={<Type className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Status"
          value={output.status}
        />
        <Meta
          icon={<Box className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Type"
          value={output.output_type}
          mono
        />
        {output.mime_type && (
          <Meta label="Format" value={output.mime_type} mono />
        )}
      </dl>

      {/* ACTIONS */}
      {!failed && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-elevated px-4 py-3">
          {output.text_content && (
            <CopyButton
              text={output.text_content}
              label={`Copy ${outputTypeLabel(output.output_type)}`}
            />
          )}
          {(output.output_type === "summary" ||
            output.output_type === "advisory") && (
            <>
              <ExportButton
                outputId={output.id}
                format="docx"
                label={`Download ${outputTypeLabel(output.output_type)}`}
              />
              <ExportButton
                outputId={output.id}
                format="pdf"
                label={`Download ${outputTypeLabel(output.output_type)}`}
              />
            </>
          )}
          <DownloadButton
            output={output}
            label={`Download ${outputTypeLabel(output.output_type)}`}
          />
          {generating && (
            <p className="text-xs text-muted-foreground">
              This output is still being generated…
            </p>
          )}
          {isBinary && output.status === "completed" && !hasArtifact && (
            <p className="text-xs font-medium text-muted-foreground">
              Not available — this output has no downloadable artifact.
            </p>
          )}
        </div>
      )}

      {/* FAILURE (safe, redacted) */}
      {failed && <FailureDetails output={output} failure={failure} />}

      {/* PREVIEW */}
      {!failed && (
        <section
          aria-label="Preview"
          className="rounded-lg border border-border bg-surface-elevated px-4 py-3"
        >
          <h5 className="label-mono-sm mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            <Eye className="h-3.5 w-3.5" aria-hidden="true" />
            Preview
          </h5>
          <OutputContent output={output} />
        </section>
      )}

      {/* INTEGRITY — full readout */}
      <ArtifactIntegrity output={output} compact={false} />

      {/* VERIFICATION */}
      {!failed && <VerificationPanel outputId={output.id} />}
      {output.status === "completed" && (
        <FactVerificationPanel outputId={output.id} />
      )}
    </article>
  );
}

function Meta({
  icon,
  label,
  value,
  mono = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="flex items-center gap-1 text-[10px] uppercase tracking-wide text-muted-foreground">
        {icon}
        {label}
      </dt>
      <dd
        className={cn(
          "mt-0.5 truncate text-foreground",
          mono && "font-mono text-[11px]",
        )}
      >
        {value || "—"}
      </dd>
    </div>
  );
}