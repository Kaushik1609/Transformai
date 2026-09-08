/**
 * TransformIQ — Artifact integrity & provenance readout (Phase 12D-F).
 *
 * Displays the SHA-256 fingerprint and provenance status the backend recorded
 * for a generated artifact (``output_metadata.integrity``):
 *
 *   VERIFIED   — a digest was recorded for the artifact at generation time.
 *   UNAVAILABLE — no usable integrity record is available.
 *   ERROR      — the artifact does not match its recorded digest (tampered).
 *
 * Provenance is shown as RECORDED when the ledger (or local hash reference)
 * captured the digest, otherwise UNAVAILABLE.  No provenance claim is made
 * beyond what the backend itself recorded, and the fingerprint is truncated
 * for display but available in full on hover.
 */
"use client";

import type { OutputResponse } from "@/lib/api";
import { StatusBadge, type BadgeVariant } from "@/components/common";
import { Check, AlertTriangle, Fingerprint, ShieldOff } from "lucide-react";

type IntegrityStatus = "VERIFIED" | "UNAVAILABLE" | "ERROR";

interface IntegrityMeta {
  status?: unknown;
  digest?: unknown;
  algorithm?: unknown;
  provider?: unknown;
  reference?: unknown;
  recorded?: unknown;
}

function statusVariant(status: IntegrityStatus): BadgeVariant {
  return status === "VERIFIED"
    ? "success"
    : status === "ERROR"
      ? "error"
      : "muted";
}

function shortDigest(digest: string | null | undefined): string | null {
  if (!digest || typeof digest !== "string") return null;
  return `${digest.slice(0, 16)}…${digest.slice(-8)}`;
}

export function ArtifactIntegrity({
  output,
  compact = true,
}: {
  output: OutputResponse;
  compact?: boolean;
}) {
  const meta = (output.output_metadata ?? {}) as { integrity?: IntegrityMeta } | null;
  const integrity = meta?.integrity;
  const rawStatus = typeof integrity?.status === "string" ? integrity.status : null;
  const digest =
    typeof integrity?.digest === "string" ? integrity.digest : null;
  const provider =
    typeof integrity?.provider === "string" ? integrity.provider : "none";
  const recorded = integrity?.recorded === true;

  let status: IntegrityStatus;
  let note: string;
  if (rawStatus === "tampered") {
    status = "ERROR";
    note = "This artifact does not match its recorded digest.";
  } else if (rawStatus === "recorded" || rawStatus === "local") {
    status = "VERIFIED";
    note = "SHA-256 digest was recorded at generation time.";
  } else {
    status = "UNAVAILABLE";
    note = "No usable integrity record exists for this artifact.";
  }

  const provenance: "RECORDED" | "UNAVAILABLE" =
    recorded && status === "VERIFIED" ? "RECORDED" : "UNAVAILABLE";

  if (compact) {
    const Icon =
      status === "VERIFIED"
        ? Check
        : status === "ERROR"
          ? AlertTriangle
          : ShieldOff;
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5 text-[11px] font-medium text-muted-foreground"
        title={note}
      >
        <Icon
          className={`h-3 w-3 ${
            status === "VERIFIED"
              ? "text-success"
              : status === "ERROR"
                ? "text-destructive"
                : ""
          }`}
          aria-hidden="true"
        />
        Integrity · {status}
      </span>
    );
  }

  return (
    <div className="rounded-md border border-border bg-muted/30 px-3 py-2 text-[11px]">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 font-semibold text-foreground">
          <Fingerprint className="h-3.5 w-3.5" aria-hidden="true" />
          Artifact integrity
        </p>
        <StatusBadge variant={statusVariant(status)}>{status}</StatusBadge>
      </div>
      <dl className="mt-2 space-y-1 text-muted-foreground">
        <Row
          label="SHA-256"
          value={
            digest
              ? `${shortDigest(digest)} (${digest})`
              : "Not recorded"
          }
        />
        <Row label="Provenance" value={provenance} />
        <Row label="Recorded at" value={note} />
        {provider && provider !== "none" && (
          <Row label="Ledger provider" value={provider} />
        )}
      </dl>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 uppercase tracking-wide">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}