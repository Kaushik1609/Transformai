/**
 * TransformIQ — Trust status + Cross-Output Consistency panel (Phase 12B).
 *
 * Displays the deterministic trust status for each completed output (TRUSTED /
 * CAUTION / UNVERIFIED) and a cross-output consistency summary for the whole
 * transformation job.  All signals come from the backend response — nothing is
 * invented client-side — and no general-semantic scores are shown.
 */
"use client";

import { useState } from "react";
import {
  type ConsistencyResponse as ConsistencyApiResponse,
  transformationsApi,
  ApiError,
} from "@/lib/api";
import { StatusBadge } from "@/components/common";
import { Check, AlertTriangle, Loader2 } from "lucide-react";
import { TrustStatus } from "./TrustStatus";

interface ConsistencyPanelProps {
  jobId: string;
}

export function ConsistencyPanel({ jobId }: ConsistencyPanelProps) {
  const [data, setData] = useState<ConsistencyApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function runCheck() {
    setLoading(true);
    setError(null);
    try {
      const result = await transformationsApi.consistency(jobId);
      setData(result);
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Consistency check could not be completed.",
      );
    } finally {
      setLoading(false);
    }
  }

  if (!data) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void runCheck()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-muted/70 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          ) : (
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
          )}
          {loading ? "Checking…" : "Check consistency"}
        </button>
        {error && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {error}
          </p>
        )}
      </div>
    );
  }

  return <ResultView data={data.data} />;
}

function ResultView({ data }: { data: ConsistencyApiResponse["data"] }) {
  const cross = data.cross_output;
  const crossVariant =
    cross.status === "CONSISTENT"
      ? "success"
      : cross.status === "INCONSISTENT"
        ? "warning"
        : "muted";

  return (
    <div className="space-y-3 rounded-md border border-border bg-muted/30 px-3 py-2">
      {/* Cross-output consistency */}
      <div>
        <div className="flex items-center gap-2">
          <p className="text-xs font-semibold text-foreground">
            Cross-output consistency
          </p>
          <StatusBadge variant={crossVariant}>{cross.status}</StatusBadge>
        </div>
        {cross.status === "CONSISTENT" && (
          <p className="mt-1 flex items-center gap-1.5 text-[11px] text-success">
            <Check className="h-3.5 w-3.5" aria-hidden="true" />
            Consistent across {cross.completed_output_count} completed outputs.
          </p>
        )}
        {cross.status === "INCONSISTENT" && (
          <div className="mt-1 space-y-1">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-destructive">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
              {cross.conflicts.length} conflict
              {cross.conflicts.length !== 1 ? "s" : ""} detected across completed
              outputs.
            </p>
            <ul className="space-y-1">
              {cross.conflicts.slice(0, 5).map((conflict, i) => (
                <li
                  key={i}
                  className="text-[11px] text-muted-foreground"
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
          <p className="mt-1 text-[11px] text-muted-foreground">
            Not applicable — requires at least two completed outputs.
          </p>
        )}
      </div>

      {/* Trust statuses (Phase 12D-B — full readout per output) */}
      {data.trust_statuses.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-foreground">
            Trust status per output
          </p>
          <div className="mt-1.5 space-y-2">
            {data.trust_statuses.map((trust) => (
              <TrustStatus key={trust.output_id} trust={trust} />
            ))}
          </div>
        </div>
      )}

      <p className="text-[10px] text-muted-foreground">
        Deterministic signal-based assessment — no arbitrary trust scores.
      </p>
    </div>
  );
}
