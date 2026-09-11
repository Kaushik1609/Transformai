/**
 * TransformIQ — Security Activity page.
 *
 * Provides a dedicated view of the security activity ledger, DLP scrubbing,
 * and provenance audit trail backed by real operations API events.
 */
"use client";

import { AppShell } from "@/components/layout";
import { SecurityActivity } from "@/components/verification/SecurityActivity";
import { ShieldCheck, Lock, CheckCircle2, ShieldAlert } from "lucide-react";

export default function SecurityPage() {
  return (
    <AppShell active="/security" title="Security Activity" subtitle="High-assurance audit ledger and DLP telemetry">
      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="label-mono-xs uppercase text-secondary-fixed-dim">
                Zero-Trust Audit Log
              </span>
              <span className="h-1.5 w-1.5 rounded-full bg-secondary animate-pulse" />
            </div>
            <h1 className="headline-xl font-semibold text-foreground tracking-tight">
              Security Activity
            </h1>
            <p className="text-sm text-muted-foreground max-w-2xl leading-relaxed">
              Continuous monitoring of cryptographic hash stamping, malware screening,
              adversarial prompt defense, and data loss prevention (DLP) redaction events.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 rounded bg-surface-container-high px-2.5 py-1 text-xs text-on-surface">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400" />
              <span className="font-label-mono-sm uppercase">Audit Log On</span>
            </div>
            <div className="flex items-center gap-1.5 rounded bg-surface-container-low px-2.5 py-1 text-xs text-secondary-fixed-dim">
              <ShieldCheck className="h-3.5 w-3.5" />
              <span className="font-label-mono-sm uppercase">DLP Gateway Active</span>
            </div>
          </div>
        </div>

        {/* Security Posture Summary Tiles */}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-border bg-surface-container p-4 shadow-sm">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="label-mono-xs uppercase">Engine Sandbox</span>
              <Lock className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 text-xl font-semibold text-foreground">
              Enabled
            </div>
            <p className="mt-1 text-xs text-secondary-fixed-dim font-label-mono-sm">
              Backed by operations events
            </p>
          </div>

          <div className="rounded-xl border border-border bg-surface-container p-4 shadow-sm">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="label-mono-xs uppercase">Malware & Threat Scan</span>
              <ShieldCheck className="h-4 w-4 text-emerald-400" />
            </div>
            <div className="mt-2 text-xl font-semibold text-foreground">
              ClamAV & YARA
            </div>
            <p className="mt-1 text-xs text-emerald-400 font-label-mono-sm">
              In-Memory Stream Verification
            </p>
          </div>

          <div className="rounded-xl border border-border bg-surface-container p-4 shadow-sm">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="label-mono-xs uppercase">DLP Masking</span>
              <CheckCircle2 className="h-4 w-4 text-secondary-fixed-dim" />
            </div>
            <div className="mt-2 text-xl font-semibold text-foreground">
              Presidio Enforced
            </div>
            <p className="mt-1 text-xs text-muted-foreground font-label-mono-sm">
              Auto PII Redaction
            </p>
          </div>

          <div className="rounded-xl border border-border bg-surface-container p-4 shadow-sm">
            <div className="flex items-center justify-between text-muted-foreground">
              <span className="label-mono-xs uppercase">Integrity Seals</span>
              <ShieldAlert className="h-4 w-4 text-primary" />
            </div>
            <div className="mt-2 text-xl font-semibold text-foreground">
              SHA-256 Validated
            </div>
            <p className="mt-1 text-xs text-primary font-label-mono-sm">
              Digest recorded at generation
            </p>
          </div>
        </div>

        {/* Security Events Audit Trail */}
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="headline-md font-semibold text-foreground">
              Recent Security & Provenance Events
            </h2>
            <span className="label-mono-xs uppercase text-muted-foreground">
              Live Audit Trail
            </span>
          </div>

          <div className="rounded-xl border border-border bg-surface-container-low p-4 shadow-sm">
            <SecurityActivity limit={50} />
          </div>
        </section>
      </div>
    </AppShell>
  );
}
