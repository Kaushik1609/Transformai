/**
 * TransformIQ — Fact verification panel (Phase 11N).
 *
 * On-demand, deterministic evidence-based fact verification for a completed
 * output. Runs POST /api/v1/outputs/{output_id}/verify-facts, which extracts
 * factual claims from the output, retrieves project-scoped source evidence via
 * the RAG path, and assigns a three-state verdict to each claim:
 *
 *   SUPPORTED    — the claim overlaps retrieved source evidence with no
 *                  numeric/date conflict.
 *   CONTRADICTED — the claim's numbers/dates conflict with the evidence.
 *   UNVERIFIED   — no overlapping source evidence was retrieved.
 *
 * This is intentionally NOT a claim of ground-truth correctness. It reports
 * whether a generated statement is supported by the project's own sources.
 */
"use client";

import { useState } from "react";
import {
  type FactVerificationResponse,
  outputsApi,
  ApiError,
} from "@/lib/api";
import { verificationStatusVariant } from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import { Check, AlertTriangle, HelpCircle, ShieldQuestion } from "lucide-react";

interface FactVerificationPanelProps {
  outputId: string;
}

export function FactVerificationPanel({
  outputId,
}: FactVerificationPanelProps) {
  const [report, setReport] = useState<FactVerificationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runVerification() {
    setLoading(true);
    setError(null);
    try {
      const result = await outputsApi.verifyFacts(outputId);
      setReport(result);
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Fact verification could not be completed.",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!report) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void runVerification()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/70 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <ShieldQuestion className="h-3.5 w-3.5" aria-hidden="true" />
          {loading ? "Verifying facts…" : "Verify facts"}
        </button>
        {error && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {error}
          </p>
        )}
      </div>
    );
  }

  return <ReportView report={report} />;
}

function ReportView({ report }: { report: FactVerificationResponse }) {
  const data = report.data;
  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">Fact verification</p>
        <StatusBadge variant={verificationStatusVariant(data.overall_status)}>
          {data.overall_status}
        </StatusBadge>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{data.summary}</p>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Metric label="Checked" value={data.claims_checked} />
        <Metric label="Supported" value={data.claims_supported} />
        <Metric label="Contradicted" value={data.claims_contradicted} />
        <Metric label="Unverified" value={data.claims_unverified} />
      </dl>
      {data.claims.length > 0 && (
        <ul className="mt-2 space-y-1.5">
          {data.claims.map((claim) => (
            <ClaimRow key={claim.id} claim={claim} />
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] text-muted-foreground">
        Evidence-based check against this project&apos;s sources — not a claim of
        ground-truth correctness.
      </p>
    </div>
  );
}

function ClaimRow({
  claim,
}: {
  claim: FactVerificationResponse["data"]["claims"][number];
}) {
  const icon =
    claim.verdict === "SUPPORTED" ? (
      <Check className="h-3.5 w-3.5 shrink-0 text-success" aria-hidden="true" />
    ) : claim.verdict === "CONTRADICTED" ? (
      <AlertTriangle
        className="h-3.5 w-3.5 shrink-0 text-destructive"
        aria-hidden="true"
      />
    ) : (
      <HelpCircle
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
    );

  return (
    <li className="flex gap-2 text-[11px] leading-relaxed text-muted-foreground">
      {icon}
      <span>
        <span className="text-foreground">{claim.text}</span>
        <span className="ml-1.5 uppercase tracking-wide">
          {claim.verdict}
        </span>
        <span className="block">{claim.reason}</span>
        {claim.evidence.length > 0 && (
          <ul className="mt-0.5 space-y-0.5 text-muted-foreground/80">
            {claim.evidence.map((evidence) => (
              <li key={evidence.chunk_id}>
                Evidence: {evidence.evidence}
              </li>
            ))}
          </ul>
        )}
      </span>
    </li>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="text-xs font-medium text-foreground">{value}</dd>
    </div>
  );
}