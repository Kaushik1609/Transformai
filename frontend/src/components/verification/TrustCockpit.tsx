/**
 * TransformIQ — Trust / Verification Cockpit (UI-6).
 *
 * A composition layer, NOT a verification engine. It reuses the existing
 * backend-driven readouts — per-output TrustStatus, cross-output consistency,
 * fact verification (on demand), the security pipeline, security activity and
 * artifact integrity — and arranges them into a single controlled hierarchy:
 *
 *   TRUST STATUS → WHY THIS STATUS → CROSS-OUTPUT CONSISTENCY →
 *   FACT VERIFICATION → SECURITY SIGNALS → ARTIFACT INTEGRITY →
 *   WHAT REMAINS UNVERIFIED
 *
 * Every value rendered comes from real backend/job/output signals. Nothing is
 * estimated client-side: no trust percentages, no invented readiness, no
 * "blockchain VERIFIED" claims. Absence of a signal is shown as UNAVAILABLE
 * and never as success.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type ConsistencyResultResponse,
  type OutputResponse,
  type TrustStatusResponse,
  type TransformationJobResponse,
  transformationsApi,
  ApiError,
} from "@/lib/api";
import { outputTypeLabel } from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import {
  BadgeCheck,
  Check,
  Fingerprint,
  GitCompare,
  HelpCircle,
  Info,
  Loader2,
  Shield,
  ShieldCheck,
} from "lucide-react";
import { TrustStatus } from "./TrustStatus";
import { SecurityPipeline } from "./SecurityPipeline";
import { SecurityActivity } from "./SecurityActivity";
import { FactVerificationPanel } from "./FactVerificationPanel";
import { ArtifactIntegrity } from "./ArtifactIntegrity";

interface TrustCockpitProps {
  job: TransformationJobResponse;
  outputs: OutputResponse[];
  className?: string;
}

interface TrustCounts {
  trusted: number;
  caution: number;
  unverified: number;
}

/**
 * Aggregate the deterministic trust statuses the backend recorded per output.
 * Exported as a pure helper so the mapping is unit-testable.
 */
export function trustCounts(
  statuses: TrustStatusResponse[],
): TrustCounts {
  const counts: TrustCounts = { trusted: 0, caution: 0, unverified: 0 };
  for (const status of statuses) {
    if (status.status === "TRUSTED") counts.trusted += 1;
    else if (status.status === "CAUTION") counts.caution += 1;
    else counts.unverified += 1;
  }
  return counts;
}

function isConsistencyPayload(
  value: unknown,
): value is ConsistencyResultResponse {
  if (!value || typeof value !== "object") return false;
  const record = value as Partial<ConsistencyResultResponse>;
  return (
    Array.isArray(record.trust_statuses) &&
    !!record.cross_output &&
    typeof record.cross_output === "object"
  );
}

export function TrustCockpit({
  job,
  outputs,
  className,
}: TrustCockpitProps) {
  const [consistency, setConsistency] =
    useState<ConsistencyResultResponse | null>(null);
  const [consistencyError, setConsistencyError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const runConsistency = useCallback(async () => {
    setLoading(true);
    setConsistencyError(null);
    try {
      const res = await transformationsApi.consistency(job.id);
      setConsistency(isConsistencyPayload(res?.data) ? res.data : null);
    } catch (err: unknown) {
      setConsistencyError(
        err instanceof ApiError
          ? err.detail
          : "The trust assessment could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }, [job.id]);

  useEffect(() => {
    void runConsistency();
  }, [runConsistency]);

  const trustStatuses = consistency?.trust_statuses ?? [];
  const counts = trustCounts(trustStatuses);
  const cross = consistency?.cross_output ?? null;
  const crossVariant =
    cross?.status === "CONSISTENT"
      ? "success"
      : cross?.status === "INCONSISTENT"
        ? "warning"
        : "muted";

  const completedOutputs = outputs.filter((o) => o.status === "completed");
  const failedOutputs = outputs.filter((o) => o.status === "failed");

  const unverifiedIntegrity = completedOutputs.filter((output) => {
    const meta = (output.output_metadata ?? {}) as {
      integrity?: { status?: unknown };
    } | null;
    const raw = meta?.integrity?.status;
    return !(raw === "recorded" || raw === "local");
  });

  const missingSignalLabels = Array.from(
    new Set(
      trustStatuses.flatMap((t) =>
        t.signals
          .filter((s) => s.status === "missing")
          .map((s) => s.category),
      ),
    ),
  );

  return (
    <div className={className}>
      <div className="flex flex-col gap-2">
        <TrustCockpitSection
          icon={<ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Trust status"
          aside={
            loading || !consistency ? undefined : (
              <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
                Trusted {counts.trusted} · Caution {counts.caution} ·
                Unverified {counts.unverified}
              </span>
            )
          }
        >
          {loading ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2
                className="h-3.5 w-3.5 animate-spin"
                aria-hidden="true"
              />
              Loading trust status…
            </p>
          ) : consistencyError ? (
            <div className="flex flex-wrap items-center gap-2">
              <p role="alert" className="text-xs font-medium text-destructive">
                Trust status could not be loaded.
              </p>
              <button
                type="button"
                onClick={() => void runConsistency()}
                className="rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground transition-colors hover:bg-muted/70"
              >
                Try again
              </button>
            </div>
          ) : trustStatuses.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No per-output trust status is recorded for this job.
            </p>
          ) : (
            <div className="space-y-2">
              {trustStatuses.map((trust) => (
                <TrustStatus key={trust.output_id} trust={trust} />
              ))}
            </div>
          )}
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<Info className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Why this status"
        >
          <WhyThisStatus
            statuses={trustStatuses}
            counts={counts}
            blocked={!!consistencyError && trustStatuses.length === 0}
          />
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<GitCompare className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Cross-output consistency"
          aside={cross ? <StatusBadge variant={crossVariant}>{cross.status}</StatusBadge> : undefined}
        >
          {loading && !cross ? (
            <p className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2
                className="h-3.5 w-3.5 animate-spin"
                aria-hidden="true"
              />
              Checking consistency…
            </p>
          ) : consistencyError && !cross ? (
            <div className="flex flex-wrap items-center gap-2">
              <p role="alert" className="text-xs font-medium text-destructive">
                Cross-output consistency is unavailable.
              </p>
              <button
                type="button"
                onClick={() => void runConsistency()}
                className="rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs text-foreground transition-colors hover:bg-muted/70"
              >
                Try again
              </button>
            </div>
          ) : cross ? (
            <ConsistencyView cross={cross} />
          ) : (
            <p className="text-xs text-muted-foreground">
              Cross-output consistency has not been recorded for this job.
            </p>
          )}
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Fact verification"
        >
          {completedOutputs.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No completed outputs — there is nothing to verify yet.
            </p>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Fact checking runs on demand per output. A check that has not
                run is not a judgement about the content.
              </p>
              {completedOutputs.map((output) => (
                <div key={output.id} className="rounded-md border border-border/60 bg-muted/20 p-3">
                  <p className="mb-2 text-xs font-medium text-foreground">
                    {outputTypeLabel(output.output_type)}
                  </p>
                  <FactVerificationPanel outputId={output.id} />
                </div>
              ))}
            </div>
          )}
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<Shield className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Security signals"
        >
          <div className="space-y-3">
            <SecurityPipeline
              projectId={job.project_id}
              jobSourceId={job.source_id}
              outputs={outputs}
            />
            <SecurityActivity projectId={job.project_id} limit={15} />
          </div>
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<Fingerprint className="h-3.5 w-3.5" aria-hidden="true" />}
          label="Artifact integrity & provenance"
        >
          {outputs.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No artifacts were generated.
            </p>
          ) : (
            <div className="space-y-2">
              {completedOutputs.map((output) => (
                <ArtifactIntegrity
                  key={output.id}
                  output={output}
                  compact={false}
                />
              ))}
              {failedOutputs.length > 0 && (
                <p className="text-xs text-muted-foreground">
                  {failedOutputs.length} failed output
                  {failedOutputs.length !== 1 ? "s" : ""} produced no artifact —
                  integrity is unavailable for them.
                </p>
              )}
              {completedOutputs.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No completed artifact to fingerprint.
                </p>
              )}
            </div>
          )}
        </TrustCockpitSection>

        <Connector />

        <TrustCockpitSection
          icon={<HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />}
          label="What remains unverified"
          aside={undefined}
        >
          <UnverifiedList
            job={job}
            completedOutputs={completedOutputs}
            failedCount={failedOutputs.length}
            unverifiedIntegrityCount={unverifiedIntegrity.length}
            missingSignalLabels={missingSignalLabels}
            trustRecorded={trustStatuses.length > 0}
          />
        </TrustCockpitSection>
      </div>

      <p className="mt-4 border-t border-border pt-3 text-[10px] text-muted-foreground">
        Everything shown is read from backend verification records — nothing is
        estimated client-side.
      </p>
    </div>
  );
}

function TrustCockpitSection({
  icon,
  label,
  aside,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface-elevated p-4">
      <div className="mb-3 flex items-center justify-between gap-2 border-b border-border/60 pb-2">
        <h4 className="label-mono-sm flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
          {icon}
          {label}
        </h4>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Connector() {
  return (
    <div
      className="mx-auto h-5 w-px bg-border"
      aria-hidden="true"
    />
  );
}

function WhyThisStatus({
  statuses,
  counts,
  blocked,
}: {
  statuses: TrustStatusResponse[];
  counts: TrustCounts;
  blocked: boolean;
}) {
  if (blocked) {
    return (
      <p className="text-xs text-muted-foreground">
        The backend trust assessment could not be loaded, so reasons cannot be
        shown.
      </p>
    );
  }
  if (statuses.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No backend trust assessment was recorded, so no reasons are available.
      </p>
    );
  }

  const reasonCounts = new Map<string, number>();
  for (const t of statuses) {
    for (const code of t.reason_codes) {
      reasonCounts.set(code, (reasonCounts.get(code) ?? 0) + 1);
    }
  }

  const missingSignalLabels = Array.from(
    new Set(
      statuses.flatMap((t) =>
        t.signals
          .filter((s) => s.status === "missing")
          .map((s) => s.category),
      ),
    ),
  );

  return (
    <div className="space-y-2">
      {reasonCounts.size > 0 ? (
        <div>
          <p className="mb-1 text-xs font-semibold text-foreground">
            Reasons reported by the backend
          </p>
          <ul className="space-y-1">
            {Array.from(reasonCounts.entries()).map(([code, n]) => (
              <li
                key={code}
                className="flex items-center gap-2 text-xs text-muted-foreground"
              >
                <span className="font-mono">{code}</span>
                <span>· {n} output{n !== 1 ? "s" : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">
          No reason codes were recorded.
        </p>
      )}

      {missingSignalLabels.length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Signals with no recorded result:{" "}
          <span className="font-mono">{missingSignalLabels.join(", ")}</span>
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Every recorded signal category has a result.
        </p>
      )}

      {counts.unverified > 0 && (
        <p className="text-xs text-muted-foreground">
          Unverified outputs have no recorded verification signal — that is not
          a claim that the content is wrong.
        </p>
      )}
    </div>
  );
}

function ConsistencyView({
  cross,
}: {
  cross: ConsistencyResultResponse["cross_output"];
}) {
  return (
    <div className="space-y-2">
      {cross.status === "CONSISTENT" && (
        <p className="flex items-center gap-1.5 text-xs text-success">
          <Check className="h-3.5 w-3.5" aria-hidden="true" />
          Consistent across {cross.completed_output_count} completed output
          {cross.completed_output_count !== 1 ? "s" : ""}.
        </p>
      )}
      {cross.status === "INCONSISTENT" && (
        <div className="space-y-1">
          <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
            <HelpCircle className="h-3.5 w-3.5" aria-hidden="true" />
            {cross.conflicts.length} conflict
            {cross.conflicts.length !== 1 ? "s" : ""} detected across completed
            outputs.
          </p>
          <ul className="space-y-1">
            {cross.conflicts.slice(0, 5).map((conflict, i) => (
              <li
                key={`${conflict.output_a_id}-${conflict.output_b_id}-${i}`}
                className="text-xs text-muted-foreground"
              >
                {conflict.category} · {conflict.output_a_type} {conflict.value_a}
                {" vs "}
                {conflict.output_b_type} {conflict.value_b}
              </li>
            ))}
          </ul>
        </div>
      )}
      {cross.status === "NOT_APPLICABLE" && (
        <p className="text-xs text-muted-foreground">
          Not applicable — requires at least two completed outputs.
        </p>
      )}
      {cross.note && (
        <p className="text-[10px] text-muted-foreground">{cross.note}</p>
      )}
    </div>
  );
}

function UnverifiedList({
  job,
  completedOutputs,
  failedCount,
  unverifiedIntegrityCount,
  missingSignalLabels,
  trustRecorded,
}: {
  job: TransformationJobResponse;
  completedOutputs: OutputResponse[];
  failedCount: number;
  unverifiedIntegrityCount: number;
  missingSignalLabels: string[];
  trustRecorded: boolean;
}) {
  const items: string[] = [];

  if (!job.source_id) {
    items.push(
      "No source attached — source-grounded checks (grounding, malware, PII) could not run.",
    );
  } else {
    items.push("Source is attached — source checks are reported in Security signals.");
  }

  if (!trustRecorded) {
    items.push("No per-output trust assessment was recorded for this job.");
  }

  if (failedCount > 0) {
    items.push(
      `${failedCount} output${failedCount !== 1 ? "s" : ""} failed and has no content or verification record.`,
    );
  }

  if (unverifiedIntegrityCount > 0) {
    items.push(
      `Artifact integrity is unverified for ${unverifiedIntegrityCount} completed output${unverifiedIntegrityCount !== 1 ? "s" : ""}.`,
    );
  }

  if (missingSignalLabels.length > 0) {
    items.push(
      `No recorded signal for: ${missingSignalLabels.join(", ")}.`,
    );
  }

  if (completedOutputs.length > 0) {
    items.push(
      "Fact verification has not been run. Choose Verify facts on an output to check claims against source evidence.",
    );
  }

  if (items.length === 0) {
    items.push(
      "Nothing unverified stands out — every backend signal has a recorded result for this job.",
    );
  }

  return (
    <ul className="space-y-1.5">
      {items.map((item, index) => (
        <li
          key={index}
          className="flex items-start gap-2 text-xs text-muted-foreground"
        >
          <span
            className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-muted-foreground"
            aria-hidden="true"
          />
          {item}
        </li>
      ))}
    </ul>
  );
}