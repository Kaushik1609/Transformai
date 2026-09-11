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
      <span className="font-medium text-muted-foreground">Unavailable</span>
    );
  }
  return (
    <span className="font-medium text-muted-foreground" aria-hidden="true">
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
    <li className="group relative flex flex-col justify-between rounded bg-surface-container-low p-4 shadow-md transition-all duration-200 hover:bg-surface-container">
      <div className="space-y-3">
        <div className="flex items-start justify-between gap-2">
          <span className="label-mono-xs rounded bg-surface-container-highest px-2 py-0.5 uppercase text-muted-foreground">
            Project
          </span>
          <StatusBadge variant={isCompleted ? "success" : "info"}>
            {isCompleted ? "Completed" : "Active"}
          </StatusBadge>
        </div>

        <div>
          <Link
            href={`/projects/${project.id}`}
            className="flex items-center gap-2 font-semibold text-foreground transition-colors hover:text-primary"
          >
            <Folder className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
            <span className="truncate">{displayName}</span>
          </Link>
          {project.description && (
            <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
              {project.description}
            </p>
          )}
        </div>

        <div className="space-y-2 rounded bg-surface-container-lowest p-2.5 font-label-mono-sm text-label-mono-sm text-on-surface-variant">
          <div className="flex items-center justify-between">
            <span className="uppercase">Sources</span>
            <StatValue statsState={statsState} value={sourceCount} />
          </div>
          <div className="flex items-center justify-between">
            <span className="uppercase">Outputs</span>
            <StatValue statsState={statsState} value={outputCount} />
          </div>
        </div>

        <div className="space-y-1.5 pt-1">
          <div className="flex items-center gap-1.5 font-label-mono-sm text-label-mono-sm">
            <span className={isCompleted ? "text-success" : "text-primary"}>
              {statsState === "ok" && latestJob
                ? `Job ${latestJob.status.toUpperCase()}`
                : statsState === "unavailable"
                  ? "Unavailable"
                  : "Loading…"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            {statsState === "ok" && latestJob
              ? timeAgo(latestJob.created_at)
              : "No activity yet"}
          </div>
        </div>
      </div>

      <Link
        href={`/projects/${project.id}`}
        className="-mx-4 -mb-4 mt-4 flex w-[calc(100%+2rem)] items-center justify-center gap-2 rounded-b bg-surface-container-lowest/40 px-3 py-2.5 text-center text-sm font-medium text-primary transition-colors hover:bg-surface-container-high"
      >
        Open Project
      </Link>
    </li>
  );
}