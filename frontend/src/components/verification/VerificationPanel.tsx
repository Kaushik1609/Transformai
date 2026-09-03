/**
 * TransformIQ — Verification panel.
 *
 * Displays real Phase 8 verification results for a single output using
 * GET /api/v1/outputs/{output_id}/verification. Each record shows the overall
 * status, grounding/consistency scores as percentages, claim counts, and the
 * structured warning list produced by the verification engine.
 */
"use client";

import { useEffect, useState } from "react";
import {
  type VerificationResultResponse,
  outputsApi,
  ApiError,
} from "@/lib/api";
import {
  verificationStatusVariant,
  formatDateTime,
} from "@/lib/outputTypes";
import { LoadingSpinner, StatusBadge } from "@/components/common";

interface VerificationPanelProps {
  outputId: string;
}

interface WarningItem {
  type?: unknown;
  severity?: unknown;
  message?: unknown;
  claim_text?: unknown;
  evidence?: unknown;
  chunk_index?: unknown;
}

function formatScore(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

function warningItems(
  warnings: Record<string, unknown> | null,
): WarningItem[] {
  if (!warnings || typeof warnings !== "object") return [];
  const items = warnings["items"];
  if (!Array.isArray(items)) return [];
  return items.filter(
    (item): item is WarningItem =>
      typeof item === "object" && item !== null,
  );
}

export function VerificationPanel({ outputId }: VerificationPanelProps) {
  const [records, setRecords] = useState<VerificationResultResponse[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    outputsApi
      .verify(outputId)
      .then((res) => {
        if (!cancelled) setRecords(res.data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // No verification record exists yet for this output.
          setRecords([]);
        } else {
          setError(
            err instanceof ApiError
              ? err.detail
              : "Failed to load verification results.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [outputId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" label="Loading verification…" />
        Checking verification…
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="text-xs font-medium text-destructive">
        {error}
      </p>
    );
  }

  if (!records || records.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No verification results yet.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {records.map((record) => (
        <RecordView key={record.id} record={record} />
      ))}
    </div>
  );
}

function RecordView({ record }: { record: VerificationResultResponse }) {
  const warningsList = warningItems(record.warnings);
  const details = (record.details ?? {}) as Record<string, unknown>;
  const statusLabel =
    details["status"] === "error"
      ? `${record.overall_status} · verification error`
      : record.overall_status;
  const claimsUnsupported =
    record.claims_checked !== null &&
    record.claims_checked !== undefined &&
    record.claims_supported !== null &&
    record.claims_supported !== undefined
      ? Math.max(0, record.claims_checked - record.claims_supported)
      : null;

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">Verification</p>
        <StatusBadge variant={verificationStatusVariant(record.overall_status)}>
          {statusLabel}
        </StatusBadge>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-5">
        <Metric label="Grounding" value={formatScore(record.grounding_score)} />
        <Metric
          label="Consistency"
          value={formatScore(record.consistency_score)}
        />
        <Metric label="Claims checked" value={record.claims_checked} />
        <Metric label="Claims supported" value={record.claims_supported} />
        <Metric label="Claims unsupported" value={claimsUnsupported} />
      </dl>
      {warningsList.length > 0 && (
        <ul className="mt-2 space-y-1 text-[11px] text-muted-foreground">
          {warningsList.map((w, i) => (
            <li key={i} className="flex gap-2">
              <span aria-hidden="true">•</span>
              <span>
                {typeof w.message === "string"
                  ? w.message
                  : typeof w.type === "string"
                    ? w.type
                    : "Verification warning"}
                {typeof w.severity === "string" && (
                  <span className="ml-1 uppercase tracking-wide text-muted-foreground">
                    ({w.severity})
                  </span>
                )}
                {typeof w.evidence === "string" && w.evidence.length > 0 && (
                  <span className="block text-muted-foreground/80">
                    Evidence: {w.evidence}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">
        Checked {formatDateTime(record.created_at)}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="text-xs font-medium text-foreground">
        {value === null || value === undefined ? "—" : value}
      </dd>
    </div>
  );
}