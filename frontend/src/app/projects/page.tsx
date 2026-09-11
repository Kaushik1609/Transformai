/**
 * TransformIQ — Projects page.
 *
 * Searchable, filterable list of the user's projects with a create modal, and
 * per-project stats derived from backend data (sources, outputs, latest
 * activity).
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  type ProjectResponse,
  projectsApi,
  sourcesApi,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import { AppShell } from "@/components/layout";
import {
  EmptyState,
  ErrorState,
  LoadingSpinner,
} from "@/components/common";
import {
  ProjectCard,
  type ProjectCardMeta,
} from "@/components/projects";
import { Plus, Search, X } from "lucide-react";
import { useModalA11y } from "@/lib/useModalA11y";

type Filter = "all" | "active" | "completed";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectResponse[] | null>(null);
  const [meta, setMeta] = useState<Record<string, ProjectCardMeta>>({});
  const [loadError, setLoadError] = useState<string | null>(null);

  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  // Create modal state
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const createDialogRef = useRef<HTMLDivElement>(null);

  useModalA11y(creating, () => setCreating(false), createDialogRef);

  const loadProjects = useCallback(async () => {
    setLoadError(null);
    try {
      const res = await projectsApi.list();
      setProjects(res.data);
      // Load per-project stats. A project whose stats fail to load is shown
      // as "Unavailable" — the failure is never hidden behind fabricated zeros.
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
                  .catch(() => null)
              : 0;
            setMeta((prev) => ({
              ...prev,
              [p.id]: {
                project: p,
                statsState: "ok",
                sourceCount: sources.count,
                outputCount: jobMeta === null ? 0 : jobMeta,
                latestJob: latest,
              },
            }));
          } catch {
            setMeta((prev) => ({
              ...prev,
              [p.id]: {
                project: p,
                statsState: "unavailable",
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

  const tiles = useMemo(() => {
    const ok = Object.values(meta).filter((m) => m.statsState === "ok");
    const sources = ok.reduce((s, m) => s + m.sourceCount, 0);
    const outputs = ok.reduce((s, m) => s + m.outputCount, 0);
    const completed = ok.filter((m) => m.latestJob?.status === "completed").length;
    const statsLoaded = ok.length > 0;
    return [
      {
        label: "Projects",
        value: projects ? String(projects.length) : "—",
        bar: "w-2/5 bg-secondary",
      },
      {
        label: "Sources",
        value: statsLoaded ? String(sources) : "—",
        bar: "w-3/5 bg-primary",
      },
      {
        label: "Outputs",
        value: statsLoaded ? String(outputs) : "—",
        bar: "w-2/3 bg-tertiary-container",
      },
      {
        label: "Completed",
        value: statsLoaded ? String(completed) : "—",
        bar: "w-1/3 bg-success/70",
      },
    ];
  }, [meta, projects]);

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
        {/* Page heading */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <p className="label-mono-xs uppercase text-muted-foreground">
              Directory
            </p>
            <h1 className="headline-xl font-semibold text-foreground">
              Projects
            </h1>
            <p className="text-sm text-muted-foreground">
              Organize sources, transformations, and outputs by workspace.
            </p>
          </div>
          <span className="label-mono-xs rounded bg-surface-container-lowest px-2 py-1 uppercase text-muted-foreground shadow-sm">
            {projects ? `${projects.length} workspace${projects.length !== 1 ? "s" : ""}` : "Loading…"}
          </span>
        </div>

        {/* Summary tiles — real counts from backend data, never fabricated */}
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {tiles.map((tile) => (
            <div
              key={tile.label}
              className="relative flex flex-col justify-between overflow-hidden rounded bg-surface-container-low p-3.5 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <span className="label-mono-xs uppercase text-muted-foreground">
                  {tile.label}
                </span>
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-2xl font-semibold tracking-tight text-foreground">
                  {tile.value}
                </span>
              </div>
              <div
                aria-hidden="true"
                className="mt-2.5 h-1 w-full overflow-hidden rounded bg-surface-container-highest"
              >
                <div className={`h-full rounded ${tile.bar}`} />
              </div>
            </div>
          ))}
        </div>

        {/* Filters + search pill strip */}
        <div className="flex flex-col items-stretch justify-between gap-3 rounded bg-surface-container-low p-2 shadow-sm sm:flex-row sm:items-center">
          <div
            role="group"
            aria-label="Project filters"
            className="flex items-center gap-1.5 overflow-x-auto pb-1 sm:pb-0"
          >
            {(["all", "active", "completed"] as Filter[]).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setFilter(f)}
                className={`rounded px-3 py-1.5 text-sm capitalize transition-colors ${
                  filter === f
                    ? "bg-surface-container-lowest font-medium text-foreground shadow-sm"
                    : "text-muted-foreground hover:bg-surface-container-high hover:text-foreground"
                }`}
              >
                {f}
              </button>
            ))}
          </div>

          <div className="flex w-full items-center gap-2 rounded bg-surface-container-lowest px-3 py-1.5 shadow-inner sm:w-80">
            <Search
              className="pointer-events-none h-4 w-4 shrink-0 text-muted-foreground"
              aria-hidden="true"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search projects…"
              aria-label="Search projects"
              className="w-full border-0 bg-transparent text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
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
              <ul className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
                {filtered.map((project) => {
                  const card = meta[project.id] ?? {
                    project,
                    statsState: "loading" as const,
                    sourceCount: 0,
                    outputCount: 0,
                    latestJob: null,
                  };
                  return <ProjectCard key={project.id} meta={card} />;
                })}
              </ul>
            )}
          </>
        )}
      </div>

      {/* Create modal */}
      {creating && (
        <div
          ref={createDialogRef}
          tabIndex={-1}
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
          <div className="relative max-h-[90vh] w-full max-w-md overflow-y-auto rounded bg-surface-container-low p-6 shadow-[0_8px_32px_rgba(0,0,0,0.6)]">
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
                  className="w-full resize-y rounded-md border border-input bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
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
