/**
 * TransformIQ — DOCX/PDF export buttons (Phase 10).
 *
 * Renders Executive Summary / Advisory outputs to DOCX or PDF through the
 * backend export endpoint and triggers a browser download of the returned
 * bytes.  The document is generated server-side — no storage URL is exposed.
 */
"use client";

import { useState } from "react";
import { outputsApi, errorMessage } from "@/lib/api";
import { LoadingSpinner } from "@/components/common";
import { triggerBrowserDownload } from "./DownloadButton";

type ExportFormat = "docx" | "pdf";

const FORMAT_LABEL: Record<ExportFormat, string> = {
  docx: "DOCX",
  pdf: "PDF",
};

interface ExportButtonProps {
  outputId: string;
  format: ExportFormat;
  /** Optional label prefix (e.g. the output type name). */
  label?: string;
}

export function ExportButton({ outputId, format, label }: ExportButtonProps) {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    if (exporting) return;
    setExporting(true);
    setError(null);
    try {
      const { blob, filename } = await outputsApi.export(outputId, format);
      triggerBrowserDownload(blob, filename);
    } catch (err) {
      setError(errorMessage(err, "Document export failed. Please try again."));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={() => void handleExport()}
        disabled={exporting}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
        aria-label={label ? `${label} (${FORMAT_LABEL[format]})` : undefined}
      >
        {exporting ? (
          <LoadingSpinner size="sm" label="Exporting…" />
        ) : (
          <svg
            aria-hidden="true"
            xmlns="http://www.w3.org/2000/svg"
            className="h-3.5 w-3.5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"
            />
          </svg>
        )}
        {FORMAT_LABEL[format]}
      </button>
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}