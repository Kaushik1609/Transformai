/**
 * TransformIQ — Projects page.
 *
 * Searchable, filterable list of the user's projects with a create modal, and
 * per-project stats derived from backend data (sources, outputs, latest
 * activity).
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  type ProjectResponse,
  type SourceResponse,
  type TransformationJobResponse,
  projectsApi,
  sourcesApi,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import { timeAgo } from "@/lib/outputTypes";
import { AppShell } from "@/components/layout";
import {
  EmptyState,
  ErrorState,
  LoadingSpinner,
  StatusBadge,
} from "@/components/common";
import { isQuickProjectName } from "@/lib/quickWorkspace";
import { Plus, Folder, Search, X } from "lucide-react";

type Filter = "all" | "active" | "completed";

interface ProjectMeta {
  project: ProjectResponse;
  sourceCount: number;
  outputCount: number;
  latestJob: TransformationJobResponse | null;
}

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectResponse[] | null>(null);
  const [meta, setMeta] = useState<Record<string, ProjectMeta>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  // Create modal state
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const loadProjects = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await projectsApi.list();
      setProjects(res.data);
      // Load per-project stats
      void Promise.all(
        res.data.map(async (p) => {
          try {
            const [sources, jobs] = await Promise.all([
              sourcesApi.list(p.id),
              transformationsApi.listByProject(p.id),
            ]);
            const latest = jobs.data[0] ?? null;
            const jobMeta = latest
              ? await transformationsApi
                  .listOutputs(latest.id)
                  .then((o) => o.count)
                  .catch(() => 0)
              : 0;
            setMeta((prev) => ({
              ...prev,
              [p.id]: {
                project: p,
                sourceCount: sources.count,
                outputCount: jobMeta,
                latestJob: latest,
              },
            }));
          } catch {
            setMeta((prev) => ({
              ...prev,
              [p.id]: {
                project: p,
                sourceCount: 0,
                outputCount: 0,
                latestJob: null,
              },
            }));
          }
        }),
      );
    } catch (err) {
      setLoadError(errorMessage(err, "Failed to load projects."));
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  const filtered = useMemo(() => {
    if (!projects) return [];
    const q = search.trim().toLowerCase();
    return projects.filter((p) => {
      if (q && !p.name.toLowerCase().includes(q)) return false;
      const m = meta[p.id];
      const latest = m?.latestJob;
      if (filter === "active" && latest?.status === "completed") {
        // treat projects with no/latest non-completed job as active
        if (latest) return false;
      }
      if (filter === "completed" && (!latest || latest.status !== "completed")) {
        return false;
      }
      return true;
    });
  }, [projects, search, filter, meta]);

  const handleCreate = async () => {
    if (!name.trim() || submitting) return;
    setSubmitting(true);
    setCreateError(null);
    try {
      await projectsApi.create(name.trim(), description.trim() || null);
      setName("");
      setDescription("");
      setCreating(false);
      await loadProjects();
    } catch (err) {
      setCreateError(errorMessage(err, "Failed to create the project."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell
      active="/projects"
      title="Projects"
      subtitle="Manage your transformation projects"
      actions={
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-3.5 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          Create Project
        </button>
      }
    >
      <div className="space-y-6">
        {/* Search + filters */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative w-full max-w-sm">
            <Search
              className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search projects…"
              aria-label="Search projects"
              className="input-base pl-9"
            />
          </div>

          <div role="group" aria-label="Project filters" className="inline-flex gap-1">
            {(["all", "active", "completed"] as Filter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`rounded-md px-3 py-1.5 text-sm capitalize transition-colors ${
                  filter === f
                    ? "bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>

        {loadError && (
          <ErrorState message={loadError} onRetry={() => void loadProjects()} />
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
            description="Create your first project to organize sources and transformations."
            action={
              <button
                type="button"
                onClick={() => setCreating(true)}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Create Project
              </button>
            }
          />
        )}

        {!loadError && projects !== null && projects.length > 0 && (
          <>
            {filtered.length === 0 ? (
              <EmptyState
                title="No matching projects"
                description="Try adjusting your search or filters."
              />
            ) : (
              <ul className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {filtered.map((project) => {
                  const m = meta[project.id] ?? {
                    project,
                    sourceCount: 0,
                    outputCount: 0,
                    latestJob: null,
                  };
                  const latest = m.latestJob;
                  const isCompleted = latest?.status === "completed";
                  const displayName = isQuickProjectName(project.name)
                    ? "Quick Transformations"
                    : project.name;
                  return (
                    <li
                      key={project.id}
                      className="flex flex-col rounded-xl border border-border bg-surface-elevated p-4 transition-colors hover:border-input"
                    >
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
                          <span className="font-medium text-foreground">
                            {m.sourceCount}
                          </span>{" "}
                          Source{m.sourceCount !== 1 ? "s" : ""}
                        </span>
                        <span>
                          <span className="font-medium text-foreground">
                            {m.outputCount}
                          </span>{" "}
                          Output{m.outputCount !== 1 ? "s" : ""}
                        </span>
                      </div>

                      <p className="mt-1 text-xs text-muted-foreground">
                        {latest ? timeAgo(latest.created_at) : "No activity yet"}
                      </p>

                      <Link
                        href={`/projects/${project.id}`}
                        className="mt-4 inline-flex items-center justify-center rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
                      >
                        Open Project
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </div>

      {/* Create modal */}
      {creating && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Create project"
        >
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setCreating(false)}
            aria-hidden="true"
          />
          <div className="relative w-full max-w-md rounded-xl border border-border bg-surface-elevated p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-foreground">
                Create a new project
              </h2>
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Close"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <label
                  htmlFor="project-name"
                  className="mb-1 block text-sm font-medium text-foreground"
                >
                  Project name
                </label>
                <input
                  id="project-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Q3 Product Launch"
                  className="input-base"
                />
              </div>
              <div>
                <label
                  htmlFor="project-description"
                  className="mb-1 block text-sm font-medium text-foreground"
                >
                  Description
                </label>
                <textarea
                  id="project-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What is this project about? (optional)"
                  rows={3}
                  className="w-full resize-y rounded-md border border-input bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>
            </div>

            {createError && (
              <p role="alert" className="mt-3 text-xs font-medium text-destructive">
                {createError}
              </p>
            )}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => setCreating(false)}
                className="rounded-md border border-border bg-background px-4 py-2 text-sm text-foreground transition-colors hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleCreate()}
                disabled={submitting || !name.trim()}
                className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting && <LoadingSpinner size="sm" label="Creating…" />}
                {submitting ? "Creating…" : "Create Project"}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
