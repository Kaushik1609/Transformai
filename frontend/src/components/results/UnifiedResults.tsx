/**
 * TransformIQ — Unified results workspace.
 *
 * Shows all generated outputs for a transformation in a single tabbed area so
 * the user can switch between results without leaving the page. Each tab shows
 * that output's content and actions (copy / export / download).
 */
"use client";

import { useState } from "react";
import {
  type OutputResponse,
  type TransformationJobResponse,
} from "@/lib/api";
import { isTerminalJobStatus, outputTypeShortLabel } from "@/lib/outputTypes";
import { cn } from "@/lib/utils";
import { Check, AlertTriangle } from "lucide-react";
import { ResultsPanel } from "./ResultsPanel";
import { ConsistencyPanel } from "@/components/verification/ConsistencyPanel";
import { SecurityPipeline } from "@/components/verification/SecurityPipeline";
import { SecurityActivity } from "@/components/verification/SecurityActivity";

interface UnifiedResultsProps {
  job: TransformationJobResponse;
  outputs: OutputResponse[];
  loading?: boolean;
}

function tabIcon(status: string) {
  if (status === "completed") return <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />;
  if (status === "failed") return <AlertTriangle className="h-3.5 w-3.5 text-destructive" aria-hidden="true" />;
  return null;
}

export function UnifiedResults({ job, outputs, loading = false }: UnifiedResultsProps) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  if (isTerminalJobStatus(job.status)) {
    if (outputs.length === 0 && loading) {
      return <p className="text-xs text-muted-foreground">Loading outputs…</p>;
    }
    if (outputs.length === 0) {
      return <p className="text-xs text-muted-foreground">No outputs were generated.</p>;
    }

    const completed = outputs.filter((o) => o.status === "completed").length;
    const failed = outputs.filter((o) => o.status === "failed").length;
    const activeId = selectedId ?? outputs[0].id;
    const activeOutput = outputs.find((o) => o.id === activeId) ?? outputs[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="text-sm font-semibold text-foreground">
          {completed} output{completed !== 1 ? "s" : ""} generated
        </h3>
        {failed > 0 && (
          <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs text-destructive">
            {failed} failed
          </span>
        )}
      </div>

      {/* Phase 12B — job-level trust + cross-output consistency */}
      <ConsistencyPanel jobId={job.id} />

      {/* Phase 12D — security pipeline (7 stages) + security activity */}
      <SecurityPipeline
        projectId={job.project_id}
        jobSourceId={job.source_id}
        outputs={outputs}
      />
      <SecurityActivity projectId={job.project_id} limit={15} />

      {/* Output tabs */}
        <div role="tablist" aria-label="Generated outputs" className="flex flex-wrap gap-1.5">
          {outputs.map((output) => {
            const active = output.id === activeId;
            return (
              <button
                key={output.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setSelectedId(output.id)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
                  active
                    ? "border-primary/50 bg-primary/10 text-foreground"
                    : "border-border bg-surface-elevated text-muted-foreground hover:border-input hover:text-foreground",
                )}
              >
                {tabIcon(output.status)}
                {outputTypeShortLabel(output.output_type)}
              </button>
            );
          })}
        </div>

        <div role="tabpanel">
          <ResultsPanel outputs={[activeOutput]} loading={false} />
        </div>
      </div>
    );
  }

  return null;
}
