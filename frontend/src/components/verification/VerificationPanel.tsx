/**
 * TransformIQ — Verification panel.
 *
 * Displays verification results for a single output using
 * GET /api/v1/outputs/{output_id}/verification. When the backend reports the
 * pending Phase 8 state it is shown clearly as pending rather than pretending
 * verification completed.
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

function isPendingPhase8(
  record: VerificationResultResponse,
): boolean {
  const details = (record.details ?? {}) as Record<string, unknown>;
  const warnings = (record.warnings ?? {}) as Record<string, unknown>;
  return details["status"] === "pending_phase8" ||
    warnings["status"] === "pending_phase8" ||
    record.overall_status === "pending";
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
      {records.map((record) =>
        isPendingPhase8(record) ? (
          <div
            key={record.id}
            className="rounded-md border border-border bg-muted/30 px-3 py-2"
          >
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-foreground">
                Verification pending — Phase 8 engine not implemented
              </p>
              <StatusBadge variant="warning">
                {record.overall_status}
              </StatusBadge>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              The verification engine (claim extraction, grounding and
              consistency scoring) is implemented in a later phase.
            </p>
          </div>
        ) : (
          <WarningView key={record.id} record={record} />
        ),
      )}
    </div>
  );
}

function WarningView({ record }: { record: VerificationResultResponse }) {
  const warningsList = Array.isArray(record.warnings)
    ? (record.warnings as unknown as string[])
    : [];

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">Verification</p>
        <StatusBadge variant={verificationStatusVariant(record.overall_status)}>
          {record.overall_status}
        </StatusBadge>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Metric label="Grounding" value={record.grounding_score} />
        <Metric label="Consistency" value={record.consistency_score} />
        <Metric label="Claims checked" value={record.claims_checked} />
        <Metric label="Claims supported" value={record.claims_supported} />
      </dl>
      {warningsList.length > 0 && (
        <ul className="mt-2 list-inside list-disc space-y-0.5 text-[11px] text-muted-foreground">
          {warningsList.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[11px] text-muted-foreground">
        Checked {formatDateTime(record.created_at)}
      </p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number | null }) {
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