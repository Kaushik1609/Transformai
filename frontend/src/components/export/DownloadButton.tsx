/**
 * TransformIQ — Artifact download button (Phase 9 basic export).
 *
 * Downloads an output artifact through the API client (Phase 8E endpoint).
 * The storage key is never exposed to the browser — only the returned bytes
 * are used. Full export history/bulk export stay in Phase 10.
 */
"use client";

import { useState } from "react";
import {
  type OutputResponse,
  type ArtifactRole,
  outputsApi,
  ApiError,
} from "@/lib/api";
import { LoadingSpinner } from "@/components/common";

interface DownloadButtonProps {
  output: OutputResponse;
  label?: string;
}

export interface ArtifactOption {
  role: ArtifactRole;
  label: string;
  hint?: string;
}

function primaryLabel(mimeType: string | null): string {
  switch (mimeType) {
    case "application/vnd.openxmlformats-officedocument.presentationml.presentation":
      return "PPTX";
    case "image/png":
      return "PNG";
    case "application/pdf":
      return "PDF";
    case "text/plain":
      return "TXT";
    default:
      return "Download";
  }
}

/** Which artifacts does this output expose? (server-verified on download.) */
export function artifactOptions(output: OutputResponse): ArtifactOption[] {
  const options: ArtifactOption[] = [];
  const meta = output.output_metadata ?? {};

  if (output.storage_key && output.mime_type) {
    options.push({ role: "primary", label: primaryLabel(output.mime_type) });
  }
  if (meta["artifact"] === "infographic" && meta["pdf_storage_key"]) {
    options.push({ role: "pdf", label: "PDF" });
  }
  if (meta["artifact"] === "video" && meta["subtitle_storage_key"]) {
    options.push({ role: "srt", label: "Subtitles (SRT)" });
  }
  return options;
}

export function triggerBrowserDownload(blob: Blob, filename?: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename || `output-${Date.now()}`;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export function DownloadButton({ output, label }: DownloadButtonProps) {
  const options = artifactOptions(output);
  const [downloading, setDownloading] = useState<ArtifactRole | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleDownload = async (role: ArtifactRole) => {
    if (downloading) return;
    setDownloading(role);
    setError(null);
    try {
      const { blob, filename } = await outputsApi.download(output.id, role);
      triggerBrowserDownload(blob, filename);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Download failed.");
    } finally {
      setDownloading(null);
    }
  };

  if (options.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2">
      {options.map((option) => (
        <button
          key={option.role}
          type="button"
          onClick={() => void handleDownload(option.role)}
          disabled={downloading !== null}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
          aria-label={label ? `${label} (${option.label})` : undefined}
        >
          {downloading === option.role ? (
            <LoadingSpinner size="sm" label="Downloading…" />
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
          {option.label}
        </button>
      ))}
      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}