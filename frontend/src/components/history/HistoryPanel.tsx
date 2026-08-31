/**
 * TransformIQ — Transformation history panel (Phase 10).
 *
 * Lists the transformation jobs for the current project (newest first).
 * Selecting a historical job reloads that job's outputs in the workspace so
 * existing verification and download functionality keeps working.
 */
"use client";

import { useEffect, useState } from "react";
import {
  type TransformationJobResponse,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import {
  jobStatusVariant,
  outputTypeLabel,
  formatDateTime,
  isTerminalJobStatus,
} from "@/lib/outputTypes";
import {
  StatusBadge,
  LoadingSpinner,
  ErrorState,
  EmptyState,
} from "@/components/common";

interface HistoryPanelProps {
  projectId: string;
  /** The job currently open in the workspace (highlighted in the list). */
  currentJobId?: string | null;
  /** Called when the user selects a historical job to view. */
  onSelectJob: (job: TransformationJobResponse) => void;
}

export function HistoryPanel({
  projectId,
  currentJobId,
  onSelectJob,
}: HistoryPanelProps) {
  const [jobs, setJobs] = useState<TransformationJobResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadHistory = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await transformationsApi.listByProject(projectId);
      setJobs(res.data);
    } catch (err) {
      setError(
        errorMessage(err, "Failed to load transformation history."),
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  if (loading && jobs === null) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" label="Loading history…" />
        Loading transformation history…
      </div>
    );
  }

  if (error) {
    return (
      <ErrorState message={error} onRetry={() => void loadHistory()} />
    );
  }

  if (jobs === null || jobs.length === 0) {
    return (
      <EmptyState
        title="No transformations yet"
        description="History will appear here after you generate outputs."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {jobs.map((job) => (
        <li key={job.id} className="min-w-0">
          <button
            type="button"
            onClick={() => onSelectJob(job)}
            aria-current={job.id === currentJobId ? "true" : undefined}
            className={`w-full rounded-md border bg-background p-3 text-left transition-colors hover:bg-muted/40 ${
              job.id === currentJobId
                ? "border-primary/50"
                : "border-border"
            }`}
          >
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <span className="flex items-center gap-2 text-xs font-medium text-foreground">
                Job {job.id.slice(0, 8)}…
                <StatusBadge variant={jobStatusVariant(job.status)}>
                  {job.status}
                </StatusBadge>
                {job.id === currentJobId && (
                  <span className="text-[11px] text-primary">(current)</span>
                )}
              </span>
              <span className="text-[11px] text-muted-foreground">
                {formatDateTime(job.created_at)}
              </span>
            </div>

            <p className="mt-1 truncate text-xs text-muted-foreground">
              {requestedOutputsLabel(job)}
            </p>

            {job.status === "failed" && job.error_message && (
              <p className="mt-1 truncate text-xs text-destructive" title={job.error_message}>
                {job.error_message}
              </p>
            )}

            {isTerminalJobStatus(job.status) && job.completed_at && (
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                Completed {formatDateTime(job.completed_at)}
              </p>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

function requestedOutputsLabel(job: TransformationJobResponse): string {
  const types = (
    (job.requested_outputs as { output_types?: string[] } | null)
      ?.output_types ?? []
  )
    .map((t) => outputTypeLabel(t))
    .filter(Boolean);
  return types.length > 0
    ? types.join(" · ")
    : "Outputs requested";
}