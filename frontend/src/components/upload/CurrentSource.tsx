/**
 * TransformIQ — Current source panel.
 *
 * Shows the selected source's file information and processing state so the
 * user always knows what material is loaded before generating.
 */
"use client";

import type { SourceResponse } from "@/lib/api";
import {
  sourceStatusVariant,
  formatFileSize,
  formatDateTime,
} from "@/lib/outputTypes";
import { LoadingSpinner, StatusBadge } from "@/components/common";

interface CurrentSourceProps {
  source: SourceResponse;
}

function displayName(source: SourceResponse): string {
  return (
    source.original_filename ||
    (source.source_type === "text" ? "Direct text" : source.source_type) ||
    "Source"
  );
}

export function CurrentSource({ source }: CurrentSourceProps) {
  const processing = source.status === "processing" || source.status === "uploaded";

  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-3">
      <div className="flex items-center justify-between gap-2">
        <p className="truncate text-sm font-medium text-foreground">
          {displayName(source)}
        </p>
        <span className="inline-flex items-center gap-2">
          {processing && <LoadingSpinner size="sm" label="Processing…" />}
          <StatusBadge variant={sourceStatusVariant(source.status)}>
            {source.status}
          </StatusBadge>
        </span>
      </div>

      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Field label="Type" value={source.source_type} />
        <Field label="Language" value={source.language} />
        <Field label="Size" value={formatFileSize(source.file_size)} />
        <Field label="Added" value={formatDateTime(source.created_at)} />
      </dl>

      {processing && (
        <p className="mt-2 text-xs text-muted-foreground">
          Processing source… you can continue configuring while it completes.
        </p>
      )}
      {source.status === "failed" && (
        <p role="alert" className="mt-2 text-xs font-medium text-destructive">
          This source failed to process. Add another source to continue.
        </p>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="truncate text-xs text-foreground">{value}</dd>
    </div>
  );
}