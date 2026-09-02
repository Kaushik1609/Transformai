/**
 * TransformIQ — Transformation progress workspace.
 *
 * Shows a live view of the multi-output orchestration: which outputs are
 * queued, generating, completed or failed, plus overall progress. Uses the real
 * backend job status + per-output status (no fake progress).
 */
"use client";

import { Check, Loader2, X } from "lucide-react";
import {
  type TransformationJobResponse,
  type OutputResponse,
} from "@/lib/api";
import { isTerminalJobStatus, outputTypeShortLabel } from "@/lib/outputTypes";
import { cn } from "@/lib/utils";
import { ProgressBar } from "@/components/common";

interface TransformationProgressProps {
  job: TransformationJobResponse;
  outputs: OutputResponse[];
}

function OutputStatusIcon({ status, type }: { status: string; type: string }) {
  if (status === "completed") {
    return <Check className="h-4 w-4 text-success" aria-hidden="true" />;
  }
  if (status === "failed") {
    return <X className="h-4 w-4 text-destructive" aria-hidden="true" />;
  }
  return (
    <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
  );
}

export function TransformationProgress({
  job,
  outputs,
}: TransformationProgressProps) {
  const running = !isTerminalJobStatus(job.status);
  const requested = (
    (job.requested_outputs as { output_types?: string[] } | null)?.output_types ?? []
  ).map((t) => outputTypeShortLabel(t));

  const completedCount = outputs.filter((o) => o.status === "completed").length;
  const failedCount = outputs.filter((o) => o.status === "failed").length;
  const total = Math.max(requested.length, outputs.length);

  return (
    <div className="space-y-4 rounded-xl border border-border bg-surface-elevated p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">
          {running ? "Transforming your source…" : "Transformation complete"}
        </h3>
        <span className="text-xs text-muted-foreground">
          {completedCount} / {total} outputs
        </span>
      </div>

      <ProgressBar value={job.progress} label="Transformation progress" />

      {running ? (
        <ul className="space-y-1.5">
          {requested.map((type) => {
            const output = outputs.find(
              (o) => outputTypeShortLabel(o.output_type) === type,
            );
            const status = output?.status ?? "queued";
            return (
              <li
                key={type}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground"
              >
                <OutputStatusIcon status={status} type={type} />
                <span className={cn(status === "queued" && "opacity-60")}>
                  {type}
                </span>
                <span
                  className={cn(
                    "ml-auto text-xs",
                    status === "completed" && "text-success",
                    status === "failed" && "text-destructive",
                    status === "queued" && "text-muted-foreground",
                  )}
                >
                  {status}
                </span>
              </li>
            );
          })}
        </ul>
      ) : (
        <ul className="space-y-1.5">
          {outputs.map((output) => {
            const type = outputTypeShortLabel(output.output_type);
            return (
              <li
                key={output.id}
                className="flex items-center gap-2.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground"
              >
                <OutputStatusIcon status={output.status} type={output.output_type} />
                <span
                  className={cn(
                    output.status === "failed" && "text-destructive",
                    output.status === "completed" && "text-foreground",
                  )}
                >
                  {type}
                </span>
                <span
                  className={cn(
                    "ml-auto text-xs",
                    output.status === "completed" && "text-success",
                    output.status === "failed" && "text-destructive",
                  )}
                >
                  {output.status}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      {!running && failedCount > 0 && completedCount > 0 && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {completedCount} output{completedCount !== 1 ? "s" : ""} completed
          {" · "}
          {failedCount} output{failedCount !== 1 ? "s" : ""} failed.{" "}
          <span className="text-muted-foreground">
            Completed outputs remain available.
          </span>
        </p>
      )}
      {!running && failedCount > 0 && completedCount === 0 && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          The transformation could not be completed.
        </p>
      )}
    </div>
  );
}
