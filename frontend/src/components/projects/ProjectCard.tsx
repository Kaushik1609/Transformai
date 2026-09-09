/**
 * TransformIQ — Project directory card (UI-7).
 *
 * One card in the projects directory. It shows the project identity and the
 * per-project stats (source/output counts, latest activity) that the backend
 * actually returned. When a project's stats could not be loaded the card says
 * "Unavailable" instead of fabricating zeros — absent data is never shown as
 * zero.
 */
"use client";

import Link from "next/link";
import type {
  ProjectResponse,
  TransformationJobResponse,
} from "@/lib/api";
import { timeAgo } from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import { isQuickProjectName } from "@/lib/quickWorkspace";
import { Folder } from "lucide-react";

export type ProjectStatsState = "loading" | "ok" | "unavailable";

export interface ProjectCardMeta {
  project: ProjectResponse;
  statsState: ProjectStatsState;
  sourceCount: number;
  outputCount: number;
  latestJob: TransformationJobResponse | null;
}

function StatValue({
  statsState,
  value,
}: {
  statsState: ProjectStatsState;
  value: number;
}) {
  if (statsState === "ok") {
    return <span className="font-medium text-foreground">{value}</span>;
  }
  if (statsState === "unavailable") {
    return (
      <span className="font-medium text-muted-foreground/70">Unavailable</span>
    );
  }
  return (
    <span className="font-medium text-muted-foreground/70" aria-hidden="true">
      …
    </span>
  );
}

export function ProjectCard({ meta }: { meta: ProjectCardMeta }) {
  const { project, statsState, sourceCount, outputCount, latestJob } = meta;
  const isCompleted = latestJob?.status === "completed";
  const displayName = isQuickProjectName(project.name)
    ? "Quick Transformations"
    : project.name;

  return (
    <li className="flex flex-col rounded-xl border border-border bg-surface-elevated p-4 transition-colors hover:border-input">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          <Folder className="h-5 w-5 text-primary" aria-hidden="true" />
          <Link
            href={`/projects/${project.id}`}
            className="font-semibold text-foreground transition-colors hover:text-primary"
          >
            {displayName}
          </Link>
        </div>
        <StatusBadge variant={isCompleted ? "success" : "info"}>
          {isCompleted ? "Completed" : "Active"}
        </StatusBadge>
      </div>

      {project.description && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
          {project.description}
        </p>
      )}

      <div className="mt-3 flex items-center gap-4 text-xs text-muted-foreground">
        <span>
          <StatValue statsState={statsState} value={sourceCount} /> Source
          {sourceCount !== 1 ? "s" : ""}
        </span>
        <span>
          <StatValue statsState={statsState} value={outputCount} /> Output
          {outputCount !== 1 ? "s" : ""}
        </span>
      </div>

      <p className="mt-1 text-xs text-muted-foreground">
        {statsState === "ok" && latestJob
          ? timeAgo(latestJob.created_at)
          : "No activity yet"}
      </p>

      <Link
        href={`/projects/${project.id}`}
        className="mt-4 inline-flex items-center justify-center rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
      >
        Open Project
      </Link>
    </li>
  );
}