/**
 * TransformIQ — Recent transformations (Phase 10 dashboard).
 *
 * Lightweight dashboard summary: for each of the user's projects it shows the
 * most recent transformation with its status and time.  Clicking a row opens
 * that project's workspace.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  type ProjectResponse,
  type TransformationJobResponse,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import {
  jobStatusVariant,
  outputTypeLabel,
  formatDateTime,
} from "@/lib/outputTypes";
import {
  StatusBadge,
  LoadingSpinner,
  ErrorState,
  EmptyState,
} from "@/components/common";

interface RecentTransformationsProps {
  projects: ProjectResponse[];
  /** How many projects to inspect for a recent job (default 5). */
  projectLimit?: number;
  /** How many rows to render (default 5). */
  rowLimit?: number;
}

interface HistoryRow {
  project: ProjectResponse;
  job: TransformationJobResponse;
}

export function RecentTransformations({
  projects,
  projectLimit = 5,
  rowLimit = 5,
}: RecentTransformationsProps) {
  const [rows, setRows] = useState<HistoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const inspected = projects.slice(0, projectLimit);
      const perProject = await Promise.all(
        inspected.map(async (project) => {
          const res = await transformationsApi.listByProject(project.id);
          return res.data[0];
        }),
      );
      const merged: HistoryRow[] = inspected
        .map((project, index) => ({ project, job: perProject[index] }))
        .filter((row): row is HistoryRow => row.job !== undefined)
        .sort(
          (a, b) =>
            new Date(b.job.created_at).getTime() -
            new Date(a.job.created_at).getTime(),
        )
        .slice(0, rowLimit);
      setRows(merged);
    } catch (err) {
      setError(
        errorMessage(err, "Failed to load recent transformations."),
      );
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (projects.length > 0) void load();
    else setLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" label="Loading recent transformations…" />
        Loading recent transformations…
      </div>
    );
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => void load()} />;
  }

  if (rows === null || rows.length === 0) {
    return (
      <EmptyState
        title="No recent transformations"
        description="Generated work will appear here across your projects."
      />
    );
  }

  return (
    <ul className="grid grid-cols-1 gap-2 md:grid-cols-2">
      {rows.map(({ project, job }) => (
        <li key={`${project.id}-${job.id}`} className="min-w-0">
          <Link
            href={`/projects/${project.id}`}
            className="block rounded-md border border-border bg-background p-3 transition-colors hover:border-primary/40 hover:bg-muted/30"
          >
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
              <span className="truncate text-xs font-semibold text-foreground">
                {project.name}
              </span>
              <StatusBadge variant={jobStatusVariant(job.status)}>
                {job.status}
              </StatusBadge>
            </div>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {requestedOutputsLabel(job)}
            </p>
            {job.status === "failed" && job.error_message && (
              <p className="mt-1 truncate text-xs text-destructive" title={job.error_message}>
                {job.error_message}
              </p>
            )}
            <p className="label-mono-sm mt-1 text-muted-foreground">
              {formatDateTime(job.created_at)}
            </p>
          </Link>
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
  return types.length > 0 ? types.join(" · ") : "Outputs requested";
}