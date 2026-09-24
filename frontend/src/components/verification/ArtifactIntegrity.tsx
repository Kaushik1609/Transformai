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
  const meta = (output.output_metadata ?? {}) as Record<string, any> | null;
  const cryptoIntegrity = meta?.cryptographic_integrity as
    | {
        status?: string;
        artifact_hash?: string;
        algorithm?: string;
        provenance_id?: string;
      }
    | undefined;
  const legacyIntegrity = meta?.integrity as IntegrityMeta | undefined;
  const digitalSig = meta?.digital_signature as
    | {
        status?: string;
        algorithm?: string;
        key_id?: string;
      }
    | undefined;

  let status: IntegrityStatus;
  let note: string;
  let digest: string | null = null;
  let provenance: "RECORDED" | "UNAVAILABLE" = "UNAVAILABLE";
  let provider = "local";

  if (cryptoIntegrity) {
    digest = typeof cryptoIntegrity.artifact_hash === "string" ? cryptoIntegrity.artifact_hash : null;
    if (cryptoIntegrity.status === "VERIFIED") {
      status = "VERIFIED";
      provenance = "RECORDED";
      note = "SHA-256 digest sealed at generation time.";
    } else if (cryptoIntegrity.status === "INVALID") {
      status = "ERROR";
      note = "Artifact digest or provenance does not match recorded seal.";
    } else {
      status = "UNAVAILABLE";
      note = "Cryptographic integrity record is incomplete or unavailable.";
    }
  } else if (legacyIntegrity) {
    const rawStatus = typeof legacyIntegrity.status === "string" ? legacyIntegrity.status : null;
    digest = typeof legacyIntegrity.digest === "string" ? legacyIntegrity.digest : null;
    provider = typeof legacyIntegrity.provider === "string" ? legacyIntegrity.provider : "none";
    const recorded = legacyIntegrity.recorded === true;

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
    provenance = recorded && status === "VERIFIED" ? "RECORDED" : "UNAVAILABLE";
  } else {
    status = "UNAVAILABLE";
    note = "No usable integrity record exists for this artifact.";
  }

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
        {digitalSig && (
          <Row
            label="Digital signature"
            value={`${digitalSig.status || "VALID"} (${digitalSig.algorithm || "Ed25519"})`}
          />
        )}
        {provider && provider !== "none" && provider !== "local" && (
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