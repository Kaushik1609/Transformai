/**
 * TransformIQ — Results panel.
 *
 * Renders the outputs of a transformation job: one card per output with its
 * type label, status, generated text content, downloadable artifacts and
 * verification state.
 */
"use client";

import type { OutputResponse } from "@/lib/api";
import {
  outputTypeLabel,
  outputStatusVariant,
} from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import { DownloadButton, CopyButton, ExportButton } from "@/components/export";
import { VerificationPanel } from "@/components/verification";

interface ResultsPanelProps {
  outputs: OutputResponse[];
  loading?: boolean;
}

const BINARY_OUTPUT_TYPES = new Set([
  "infographic",
  "presentation",
  "video",
]);

export function ResultsPanel({ outputs, loading = false }: ResultsPanelProps) {
  if (loading) {
    return (
      <p className="text-xs text-muted-foreground">Loading outputs…</p>
    );
  }

  if (outputs.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No outputs generated yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {outputs.map((output) => (
        <OutputCard key={output.id} output={output} />
      ))}
    </div>
  );
}

function OutputCard({ output }: { output: OutputResponse }) {
  const failed = output.status === "failed";
  const generating = output.status === "generating";
  const isBinary = BINARY_OUTPUT_TYPES.has(output.output_type);

  return (
    <article className="rounded-lg border border-border">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <h3 className="text-sm font-semibold text-foreground">
          {outputTypeLabel(output.output_type)}
        </h3>
        <StatusBadge variant={outputStatusVariant(output.status)}>
          {output.status}
        </StatusBadge>
      </header>

      <div className="space-y-3 px-4 py-3">
        {generating && (
          <p className="text-xs text-muted-foreground">
            This output is still being generated…
          </p>
        )}

        {failed && (
          <p role="alert" className="text-xs font-medium text-destructive">
            This output failed to generate.
          </p>
        )}

        {!failed && output.text_content && (
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 font-sans text-xs leading-relaxed text-foreground">
            {output.text_content}
          </pre>
        )}

        {!failed && !isBinary && !output.text_content && (
          <p className="text-xs text-muted-foreground">
            Content prepared — no text preview available.
          </p>
        )}

        {!failed && (
          <div className="flex flex-wrap items-center gap-2">
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
          </div>
        )}

        {!failed && <VerificationPanel outputId={output.id} />}
      </div>
    </article>
  );
}