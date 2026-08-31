/**
 * TransformIQ — Projects page (Phase 9).
 *
 * Lists the current user's projects and lets them create a new one, then
 * navigates into the transformation workspace for a selected project.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  type ProjectResponse,
  projectsApi,
  errorMessage,
} from "@/lib/api";
import { formatDateTime } from "@/lib/outputTypes";
import { DashboardLayout } from "@/components/layout";
import {
  EmptyState,
  ErrorState,
  LoadingSpinner,
  StatusBadge,
} from "@/components/common";
import { RecentTransformations } from "@/components/history";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectResponse[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await projectsApi.list();
      setProjects(res.data);
    } catch (err) {
      setLoadError(
        errorMessage(err, "Failed to load projects."),
      );
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const handleCreate = async () => {
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setCreateError(null);
    try {
      await projectsApi.create(name.trim(), description.trim() || null);
      setName("");
      setDescription("");
      await loadProjects();
    } catch (err) {
      setCreateError(
        errorMessage(err, "Failed to create the project."),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="space-y-8">
        <header className="space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-bold tracking-tight text-foreground">
              Projects
            </h1>
            <StatusBadge variant="info">Transformation workspace</StatusBadge>
          </div>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Create a project, upload a source, configure your outputs and
            generate.
          </p>
        </header>

        {/* Create project */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            New project
          </h2>
          <div className="rounded-lg border border-border bg-muted/20 p-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <input
                aria-label="Project name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Project name (required)"
                className="input-base"
              />
              <input
                aria-label="Project description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Description (optional)"
                className="input-base"
              />
            </div>
            <div className="mt-3 flex items-center gap-2">
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={submitting || !name.trim()}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting && <LoadingSpinner size="sm" label="Creating…" />}
                {submitting ? "Creating…" : "Create project"}
              </button>
              {createError && (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {createError}
                </p>
              )}
            </div>
          </div>
        </section>

        {/* Project list */}
        <section className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Your projects
          </h2>

          {loadError && (
            <ErrorState
              message={loadError}
              onRetry={() => void loadProjects()}
            />
          )}

          {!loadError && projects === null && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoadingSpinner size="sm" label="Loading projects…" />
              Loading projects…
            </div>
          )}

          {!loadError && projects !== null && projects.length === 0 && (
            <EmptyState
              title="No projects yet"
              description="Create your first project above to get started."
            />
          )}

          {!loadError && projects !== null && projects.length > 0 && (
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {projects.map((project) => (
                <li key={project.id}>
                  <Link
                    href={`/projects/${project.id}`}
                    className="block rounded-lg border border-border bg-background p-4 transition-colors hover:border-primary/40 hover:bg-muted/30"
                  >
                    <p className="text-sm font-semibold text-foreground">
                      {project.name}
                    </p>
                    {project.description && (
                      <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                        {project.description}
                      </p>
                    )}
                    <p className="mt-2 text-[11px] text-muted-foreground">
                      {formatDateTime(project.created_at)}
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Recent transformations */}
        {!loadError && projects !== null && projects.length > 0 && (
          <section className="space-y-3">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                Recent transformations
              </h2>
              <p className="text-xs text-muted-foreground">
                The most recent generation for your projects.
              </p>
            </div>
            <RecentTransformations projects={projects} />
          </section>
        )}
      </div>
    </DashboardLayout>
  );
}