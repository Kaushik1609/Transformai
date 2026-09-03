/**
 * TransformIQ — History page.
 *
 * Shows all transformations, including project transformations and
 * quick/non-project transformations, with search, status filters, and a detail
 * view that loads the actual historical outputs.
 */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  type OutputResponse,
  type ProjectResponse,
  type TransformationJobResponse,
  projectsApi,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import {
  outputTypeShortLabel,
  timeAgo,
  jobStatusVariant,
  jobCompletionStatus,
  jobCompletionVariant,
  outputStatusVariant,
} from "@/lib/outputTypes";
import { AppShell } from "@/components/layout";
import {
  EmptyState,
  ErrorState,
  LoadingSpinner,
  StatusBadge,
} from "@/components/common";
import { isQuickProjectName } from "@/lib/quickWorkspace";
import { Search, ChevronRight, X } from "lucide-react";

type Filter = "all" | "completed" | "failed";

interface HistoryEntry {
  job: TransformationJobResponse;
  project: ProjectResponse | null;
  outputs: OutputResponse[];
}

export default function HistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("all");

  // Detail
  const [detail, setDetail] = useState<HistoryEntry | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const projRes = await projectsApi.list();
      const projects = projRes.data;
      const all: HistoryEntry[] = [];
      for (const project of projects) {
        try {
          const jobs = await transformationsApi.listByProject(project.id);
          const loaded: HistoryEntry[] = [];
          for (const job of jobs.data) {
            loaded.push({ job, project, outputs: [] });
          }
          all.push(...loaded);
        } catch {
          // skip projects that fail to load their history
        }
      }
      all.sort(
        (a, b) =>
          new Date(b.job.created_at).getTime() -
          new Date(a.job.created_at).getTime(),
      );
      setEntries(all);
    } catch (err) {
      setLoadError(errorMessage(err, "Failed to load history."));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(() => {
    if (!entries) return [];
    const q = search.trim().toLowerCase();
    return entries.filter((e) => {
      if (q) {
        const outputs = e.job.requested_outputs as {
          output_types?: string[];
        } | null;
        const label = (outputs?.output_types ?? [])
          .map((t) => outputTypeShortLabel(t))
          .join(" ")
          .toLowerCase();
        const projName = (e.project?.name ?? "").toLowerCase();
        if (!label.includes(q) && !projName.includes(q)) return false;
      }
      if (filter === "completed" && e.job.status !== "completed") return false;
      if (filter === "failed" && e.job.status !== "failed") return false;
      return true;
    });
  }, [entries, search, filter]);

  const viewDetail = async (entry: HistoryEntry) => {
    setDetail(entry);
    if (entry.outputs.length > 0) return;
    setDetailLoading(true);
    try {
      const res = await transformationsApi.listOutputs(entry.job.id);
      setDetail({ ...entry, outputs: res.data });
      setEntries((prev) =>
        prev
          ? prev.map((e) =>
              e.job.id === entry.job.id ? { ...e, outputs: res.data } : e,
            )
          : prev,
      );
    } catch {
      // keep empty outputs; detail shows status only
    } finally {
      setDetailLoading(false);
    }
  };

  const displayProjectName = (entry: HistoryEntry) => {
    if (!entry.project) return "No Project";
    return isQuickProjectName(entry.project.name)
      ? "Quick Transformation"
      : entry.project.name;
  };

  const outputTypesOf = (job: TransformationJobResponse): string[] => {
    const out = (job.requested_outputs as { output_types?: string[] } | null)
      ?.output_types;
    return out ? out.map((t) => outputTypeShortLabel(t)) : [];
  };

  return (
    <AppShell
      active="/history"
      title="Transformation History"
      subtitle="All of your transformations, including quick ones"
    >
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
            placeholder="Search history…"
            aria-label="Search history"
            className="input-base pl-9"
          />
        </div>
        <div role="group" aria-label="History filters" className="inline-flex gap-1">
          {(["all", "completed", "failed"] as Filter[]).map((f) => (
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
        <ErrorState message={loadError} onRetry={() => void load()} />
      )}

      {!loadError && entries === null && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <LoadingSpinner size="sm" label="Loading history…" />
          Loading history…
        </div>
      )}

      {!loadError && entries !== null && entries.length === 0 && (
        <EmptyState
          title="No transformations yet"
          description="Your transformation history will appear here."
        />
      )}

      {!loadError && entries !== null && entries.length > 0 && (
        <>
          {filtered.length === 0 ? (
            <EmptyState
              title="No matching transformations"
              description="Try adjusting your search or filters."
            />
          ) : (
            <div className="overflow-hidden rounded-xl border border-border bg-surface-elevated">
              {/* Header row (desktop) */}
              <div className="hidden grid-cols-12 gap-3 border-b border-border px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground md:grid">
                <span className="col-span-3">Transformation</span>
                <span className="col-span-3">Project</span>
                <span className="col-span-3">Outputs</span>
                <span className="col-span-1">Status</span>
                <span className="col-span-2">Date</span>
              </div>
              <ul>
                {filtered.map((entry) => {
                  const outputs = outputTypesOf(entry.job);
                  return (
                    <li
                      key={entry.job.id}
                      className="grid grid-cols-1 gap-2 border-b border-border px-4 py-3.5 transition-colors hover:bg-muted/30 last:border-0 md:grid-cols-12 md:items-center md:gap-3"
                    >
                      <div className="col-span-3 font-medium text-foreground">
                        {outputs[0] || "Transformation"}
                      </div>
                      <div className="col-span-3 text-sm text-muted-foreground">
                        {displayProjectName(entry)}
                      </div>
                      <div className="col-span-3">
                        <div className="flex flex-wrap gap-1">
                          {outputs.map((o) => (
                            <span
                              key={o}
                              className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground"
                            >
                              {o}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="col-span-1">
                        <StatusBadge variant={jobStatusVariant(entry.job.status)}>
                          {entry.job.status}
                        </StatusBadge>
                      </div>
                      <div className="col-span-1 text-xs text-muted-foreground md:col-span-2">
                        {timeAgo(entry.job.created_at)}
                      </div>
                      <div className="col-span-3 md:col-span-0 md:hidden" />
                      <div className="col-span-3 md:col-span-12 md:mt-2 lg:col-span-0 lg:hidden">
                        <button
                          type="button"
                          onClick={() => void viewDetail(entry)}
                          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                        >
                          View
                          <ChevronRight className="h-4 w-4" aria-hidden="true" />
                        </button>
                      </div>
                      <button
                        type="button"
                        onClick={() => void viewDetail(entry)}
                        className="col-span-1 hidden items-center justify-end gap-1 text-sm font-medium text-primary hover:underline md:flex"
                      >
                        View
                        <ChevronRight className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </>
      )}

      {/* Detail drawer */}
      {detail && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-label="Transformation detail"
        >
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setDetail(null)}
            aria-hidden="true"
          />
          <div className="relative w-full max-w-2xl overflow-hidden rounded-xl border border-border bg-surface-elevated">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="text-base font-semibold text-foreground">
                Transformation
              </h2>
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                aria-label="Close detail"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="space-y-3 overflow-y-auto px-5 py-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">
                  {displayProjectName(detail)}
                </span>
                <StatusBadge
                  variant={jobCompletionVariant(
                    jobCompletionStatus(detail.job, detail.outputs),
                  )}
                >
                  {jobCompletionStatus(detail.job, detail.outputs)}
                </StatusBadge>
              </div>

              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-muted-foreground">Created</p>
                  <p className="text-foreground">
                    {new Date(detail.job.created_at).toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-muted-foreground">Completed</p>
                  <p className="text-foreground">
                    {detail.job.completed_at
                      ? new Date(detail.job.completed_at).toLocaleString()
                      : "—"}
                  </p>
                </div>
              </div>

              <div>
                <p className="mb-1 text-xs text-muted-foreground">
                  Selected outputs
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {outputTypesOf(detail.job).map((o) => (
                    <span
                      key={o}
                      className="rounded bg-muted px-2 py-0.5 text-xs text-foreground"
                    >
                      {o}
                    </span>
                  ))}
                </div>
              </div>

              {detail.job.error_message && (
                <p
                  role="alert"
                  className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive"
                >
                  {detail.job.error_message}
                </p>
              )}

              <div>
                <p className="mb-2 text-xs text-muted-foreground">
                  Generated outputs
                </p>
                {detailLoading ? (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <LoadingSpinner size="sm" />
                    Loading outputs…
                  </div>
                ) : detail.outputs.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    {(detail.job.status as string) === "failed"
                      ? "This transformation did not produce outputs."
                      : "Outputs available."}
                  </p>
                ) : (
                  <div className="space-y-2">
                    {detail.outputs.map((output) => (
                      <div
                        key={output.id}
                        className="rounded-md border border-border bg-background p-3"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-sm font-medium text-foreground">
                            {outputTypeShortLabel(output.output_type)}
                          </span>
                          <StatusBadge
                            variant={outputStatusVariant(output.status)}
                          >
                            {output.status}
                          </StatusBadge>
                        </div>
                        {output.status === "completed" && output.text_content && (
                          <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-xs text-muted-foreground">
                            {output.text_content}
                          </p>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-end">
                <Link
                  href={detail.project ? `/projects/${detail.project.id}` : "/"}
                  className="inline-flex items-center gap-1 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
                >
                  Open in project
                </Link>
              </div>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}
