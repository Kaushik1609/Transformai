/**
 * TransformIQ — Project detail route (UI-7).
 *
 * Single project view organized as:
 *
 *   PROJECT → SOURCE LIBRARY → TRANSFORMATIONS & ACTIVITY
 *
 * The source library surfaces each source's backend-recorded processing
 * status and security signals, and "Transform with this source" moves the
 * transformation workspace onto that source (optionally preset via
 * `?source=<id>` in the URL).
 */
"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import type { ProjectResponse } from "@/lib/api";
import { projectsApi, errorMessage } from "@/lib/api";
import { isQuickProjectName } from "@/lib/quickWorkspace";
import { formatDateTime, timeAgo } from "@/lib/outputTypes";
import { AppShell } from "@/components/layout";
import { StatusBadge, ErrorState, LoadingSpinner } from "@/components/common";
import { ProjectSourceLibrary } from "@/components/projects";
import { TransformationWorkspace } from "@/components/workspace";
import { Folder } from "lucide-react";

function ProjectDetailInner({ projectId }: { projectId: string }) {
  const searchParams = useSearchParams();
  const urlSource = searchParams.get("source");

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(
    urlSource,
  );

  const loadProject = useCallback(async () => {
    setError(null);
    try {
      const res = await projectsApi.get(projectId);
      setProject(res.data);
    } catch (err) {
      setError(errorMessage(err, "Failed to load this project."));
    }
  }, [projectId]);

  useEffect(() => {
    void loadProject();
  }, [loadProject]);

  const displayName = project
    ? isQuickProjectName(project.name)
      ? "Quick Transformations"
      : project.name
    : "Project";

  return (
    <div className="space-y-6">
      {error ? (
        <ErrorState message={error} onRetry={() => void loadProject()} />
      ) : !project ? (
        <div className="py-16">
          <LoadingSpinner size="lg" label="Loading project…" />
        </div>
      ) : (
        <>
          {/* PROJECT — identity header */}
          <section
            className="rounded-lg border border-border bg-surface-elevated p-4"
            aria-label="Project"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Folder className="h-5 w-5 text-primary" aria-hidden="true" />
                <h2 className="text-xl font-semibold text-foreground">
                  {displayName}
                </h2>
                <StatusBadge variant="info">OWNER-SCOPED</StatusBadge>
              </div>
            </div>
            {project.description && (
              <p className="mt-2 text-sm text-muted-foreground">
                {project.description}
              </p>
            )}
            <dl className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
              <dd>Created {formatDateTime(project.created_at)}</dd>
              <dd>Updated {timeAgo(project.updated_at)}</dd>
            </dl>
          </section>

          {/* SOURCE LIBRARY */}
          <ProjectSourceLibrary
            projectId={projectId}
            selectedSourceId={selectedSourceId}
            onTransformSource={(id) => setSelectedSourceId(id)}
          />

          {/* TRANSFORMATIONS & ACTIVITY */}
          <section aria-label="Transformations and activity">
            <div className="mb-3 flex items-center justify-between gap-2 border-b border-border pb-2">
              <h2 className="label-mono-sm text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                Transformations &amp; activity
              </h2>
            </div>
            <TransformationWorkspace
              projectId={projectId}
              key={selectedSourceId ?? "workspace-default"}
              initialSourceId={selectedSourceId}
            />
          </section>
        </>
      )}
    </div>
  );
}

export default function ProjectDetailPage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId;

  return (
    <AppShell active="/projects" title="Project">
      <Link
        href="/projects"
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        ← Projects
      </Link>
      {projectId ? (
        <Suspense
          fallback={
            <div className="py-16">
              <LoadingSpinner size="lg" label="Loading project…" />
            </div>
          }
        >
          <ProjectDetailInner projectId={projectId} />
        </Suspense>
      ) : (
        <div className="py-16">
          <LoadingSpinner size="lg" label="Loading project…" />
        </div>
      )}
    </AppShell>
  );
}