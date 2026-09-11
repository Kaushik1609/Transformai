/**
 * TransformIQ — Trust status readout for one output (Phase 12D-B).
 *
 * Renders the deterministic trust status computed by the backend
 * (TRUSTED / CAUTION / UNVERIFIED) together with every signal category the
 * backend evaluated (grounding, fact verification, integrity, security and —
 * when present — consistency/cross-output) and the exact reason codes.
 * Nothing is invented client-side and no arbitrary percentages are shown —
 * every value here comes from ``TrustStatusResponse``.
 */
"use client";

import type { TrustStatusResponse } from "@/lib/api";
import { StatusBadge, type BadgeVariant } from "@/components/common";
import { Check, AlertTriangle, HelpCircle } from "lucide-react";

const SIGNAL_LABELS: Record<string, string> = {
  grounding: "Grounding",
  fact_verification: "Fact verification",
  integrity: "Integrity",
  security: "Output security",
  consistency: "Cross-output consistency",
  output: "Output",
};

export function trustVariant(status: string): BadgeVariant {
  switch (status) {
    case "TRUSTED":
      return "success";
    case "CAUTION":
      return "warning";
    case "UNVERIFIED":
    default:
      return "muted";
  }
}

export function signalLabel(category: string): string {
  return SIGNAL_LABELS[category] ?? category;
}

interface TrustStatusProps {
  trust: TrustStatusResponse;
}

export function TrustStatus({ trust }: TrustStatusProps) {
  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge variant={trustVariant(trust.status)}>
          {trust.status}
        </StatusBadge>
        <span className="text-xs font-semibold capitalize text-foreground">
          {trust.output_type}
        </span>
        {trust.reason_codes.length > 0 && (
          <ul className="flex flex-wrap gap-1">
            {trust.reason_codes.map((code) => (
              <li
                key={code}
                className="rounded-full border border-border bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {code}
              </li>
            ))}
          </ul>
        )}
      </div>

      <ul className="mt-2 grid grid-cols-1 gap-x-4 gap-y-1 sm:grid-cols-2">
        {trust.signals.map((signal) => (
          <li
            key={signal.category}
            className="flex items-center gap-1.5 text-[11px] text-muted-foreground"
          >
            {signal.status === "positive" ? (
              <Check
                className="h-3 w-3 shrink-0 text-success"
                aria-hidden="true"
              />
            ) : signal.status === "warning" || signal.status === "failure" ? (
              <AlertTriangle
                className="h-3 w-3 shrink-0 text-destructive"
                aria-hidden="true"
              />
            ) : (
              <HelpCircle
                className="h-3 w-3 shrink-0 text-muted-foreground"
                aria-hidden="true"
              />
            )}
            <span className="font-medium capitalize">
              {signalLabel(signal.category)}
            </span>
            <span className="truncate" title={signal.detail}>
              — {signal.detail}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-1.5 text-[10px] text-muted-foreground">
        Deterministic signal-based assessment — no arbitrary trust scores.
      </p>
    </div>
  );
}