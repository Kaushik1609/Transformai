"use client";

import { useMemo } from "react";
// Removed date-fns import; using built-in Date formatting
import {
  Check,
  Loader2,
  AlertTriangle,
  Minus,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { OutputResponse, TransformationJobResponse } from "@/lib/api";

export type StageState =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped"
  | "unavailable";

export interface PipelineStage {
  id: string;
  label: string;
  status: StageState;
  detail?: string;
}

const STAGE_DEFINITIONS = [
  { id: "load", label: "Load" },
  { id: "retrieve", label: "Retrieve" },
  { id: "plan", label: "Plan" },
  { id: "generate", label: "Generate" },
  { id: "render", label: "Render" },
  { id: "validate", label: "Validate" },
] as const;

export function derivePipelineStages(
  job: TransformationJobResponse,
  outputs: OutputResponse[],
): PipelineStage[] {
  const { status, progress, source_id, error_message } = job;

  if (status === "queued" || status === "cancelled") {
    return STAGE_DEFINITIONS.map((s, index) => ({
      ...s,
      status: "pending" as StageState,
      detail:
        index === 0
          ? status === "cancelled"
            ? "Job cancelled"
            : `Waiting to start${job.started_at ? " at " + new Date(job.started_at).toLocaleString() : ""}`
          : undefined,
    }));
  }

  if (status === "running" && progress === 0) {
    return STAGE_DEFINITIONS.map((s) => ({
      ...s,
      status:
        s.id === "load" ? ("running" as StageState) : ("pending" as StageState),
      detail: s.id === "load" ? "Ingesting source" : undefined,
    }));
  }

  if (status === "running" && progress > 0) {
    const failedOutputs = outputs.filter((o) => o.status === "failed");
    const hasFailedOutputs = failedOutputs.length > 0;

    return STAGE_DEFINITIONS.map((s) => {
      if (s.id === "load" || s.id === "retrieve" || s.id === "plan") {
        if (s.id === "retrieve" && !source_id) {
          return {
            ...s,
            status: "skipped" as StageState,
            detail: "No source to retrieve",
          };
        }
        return {
          ...s,
          status: "completed" as StageState,
          detail: s.id === "retrieve" && source_id ? "Source anchored" : undefined,
        };
      }

      if (s.id === "generate") {
        return {
          ...s,
          status: hasFailedOutputs ? ("failed" as StageState) : ("running" as StageState),
          detail: hasFailedOutputs
            ? `${failedOutputs.length} output${failedOutputs.length > 1 ? "s" : ""} failed`
            : `Synthesizing ${outputs.length} output${outputs.length > 1 ? "s" : ""}`,
        };
      }

      if (s.id === "render") {
        const completedCount = outputs.filter(
          (o) => o.status === "completed",
        ).length;
        return {
          ...s,
          status: "pending" as StageState,
          detail:
            completedCount > 0 ? `${completedCount} rendered` : undefined,
        };
      }

      return { ...s, status: "pending" as StageState };
    });
  }

  if (status === "completed") {
    const hasFailedOutputs = outputs.some((o) => o.status === "failed");
    return STAGE_DEFINITIONS.map((s) => {
      if (s.id === "retrieve" && !source_id) {
        return {
          ...s,
          status: "skipped" as StageState,
          detail: "No source to retrieve",
        };
      }
      if (s.id === "generate" && hasFailedOutputs) {
        const failedCount = outputs.filter((o) => o.status === "failed").length;
        return {
          ...s,
          status: "failed" as StageState,
          detail: `${failedCount} output${failedCount > 1 ? "s" : ""} failed`,
        };
      }
      return { ...s, status: "completed" as StageState };
    });
  }

  if (status === "failed") {
    const err = error_message?.toLowerCase() ?? "";
    const isLoadFailure =
      err.includes("canonical content") || err.includes("ingestion");
    const isRetrieveFailure = err.includes("retrieve") || err.includes("anchor");
    const failedCount = outputs.filter((o) => o.status === "failed").length;
    const hasFailedOutputs = failedCount > 0;

    return STAGE_DEFINITIONS.map((s) => {
      if (isLoadFailure) {
        if (s.id === "load") {
          return {
            ...s,
            status: "failed" as StageState,
            detail: "Source ingestion failed",
          };
        }
        if (s.id === "retrieve") {
          if (!source_id) {
            return {
              ...s,
              status: "skipped" as StageState,
              detail: "No source to retrieve",
            };
          }
          return { ...s, status: "completed" as StageState };
        }
        if (s.id === "plan") {
          return { ...s, status: "completed" as StageState };
        }
        return { ...s, status: "pending" as StageState };
      }

      if (isRetrieveFailure) {
        if (s.id === "load") {
          return { ...s, status: "completed" as StageState };
        }
        if (s.id === "retrieve") {
          return {
            ...s,
            status: "failed" as StageState,
            detail: "Retrieval failed",
          };
        }
        return { ...s, status: "pending" as StageState };
      }

      if (s.id === "load" || s.id === "retrieve" || s.id === "plan") {
        if (s.id === "retrieve" && !source_id) {
          return {
            ...s,
            status: "skipped" as StageState,
            detail: "No source to retrieve",
          };
        }
        return {
          ...s,
          status: "completed" as StageState,
        };
      }
      if (s.id === "generate") {
        return {
          ...s,
          status: "failed" as StageState,
          detail: hasFailedOutputs
            ? `${failedCount} output${failedCount > 1 ? "s" : ""} failed`
            : "Generation could not be completed",
        };
      }
      return { ...s, status: "pending" as StageState };
    });
  }

  return STAGE_DEFINITIONS.map((s) => ({
    ...s,
    status: "pending" as StageState,
  }));
}

function StageIndicator({ status }: { status: StageState }) {
  const size = "h-5 w-5 flex-shrink-0";

  if (status === "completed") {
    return (
      <div
        className={cn(
          size,
          "flex items-center justify-center rounded-full bg-success/15 text-success",
        )}
      >
        <Check className="h-3 w-3" strokeWidth={2.5} />
      </div>
    );
  }

  if (status === "running") {
    return (
      <div
        className={cn(
          size,
          "flex items-center justify-center rounded-full bg-primary/15 text-primary",
        )}
      >
        <Loader2 className="h-3 w-3 animate-spin" />
      </div>
    );
  }

  if (status === "failed") {
    return (
      <div
        className={cn(
          size,
          "flex items-center justify-center rounded-full bg-destructive/15 text-destructive",
        )}
      >
        <AlertTriangle className="h-3 w-3" />
      </div>
    );
  }

  if (status === "skipped") {
    return (
      <div
        className={cn(
          size,
          "flex items-center justify-center rounded-full bg-muted/40 text-muted-foreground",
        )}
      >
        <Minus className="h-3 w-3" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        size,
        "rounded-full border border-border bg-muted/20",
      )}
    />
  );
}

function stageStatusText(status: StageState): string {
  switch (status) {
    case "completed":
      return "Completed";
    case "running":
      return "Running";
    case "failed":
      return "Failed";
    case "skipped":
      return "Skipped";
    case "unavailable":
      return "Unavailable";
    default:
      return "Pending";
  }
}

interface PipelineStageTrackProps {
  job: TransformationJobResponse;
  outputs: OutputResponse[];
  className?: string;
}

export function PipelineStageTrack({
  job,
  outputs,
  className,
}: PipelineStageTrackProps) {
  const stages = useMemo(
    () => derivePipelineStages(job, outputs),
    [job, outputs],
  );

  return (
    <div
      role="list"
      aria-label="Pipeline stages"
      className={cn("space-y-0", className)}
    >
      {stages.map((stage, index) => {
        const isLast = index === stages.length - 1;

        return (
          <div key={stage.id} role="listitem" className="flex gap-3">
            <div className="flex flex-col items-center">
              <StageIndicator status={stage.status} />
              {!isLast && (
                <div
                  className={cn(
                    "my-1 h-4 w-px",
                    stage.status === "completed"
                      ? "bg-success/30"
                      : stage.status === "running"
                        ? "bg-primary/30"
                        : "bg-border",
                  )}
                />
              )}
            </div>
            <div className="flex-1 pb-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-xs font-medium",
                    stage.status === "completed"
                      ? "text-foreground"
                      : stage.status === "running"
                        ? "text-foreground"
                        : stage.status === "failed"
                          ? "text-destructive"
                          : "text-muted-foreground",
                  )}
                >
                  {stage.label}
                </span>
                <span
                  className={cn(
                    "text-[10px] font-medium uppercase tracking-wide",
                    stage.status === "completed"
                      ? "text-success"
                      : stage.status === "running"
                        ? "text-primary"
                        : stage.status === "failed"
                          ? "text-destructive"
                          : stage.status === "skipped"
                            ? "text-muted-foreground"
                            : "text-muted-foreground",
                  )}
                >
                  {stageStatusText(stage.status)}
                </span>
              </div>
              {stage.detail && (
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {stage.detail}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
