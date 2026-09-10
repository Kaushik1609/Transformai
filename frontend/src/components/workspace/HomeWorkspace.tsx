/**
 * TransformIQ — Home transformation workspace.
 *
 * The primary AI workspace shown on Home. A single unified composer:
 *   prompt + source + tone + audience + multi-output selection
 * → one transformation (orchestration) → progress → unified results.
 *
 * Quick (non-project) transformations are stored under the auto-managed
 * "Quick Transformations" project so no manual project creation is required.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  type ConfigurationResponse,
  type OutputResponse,
  type OutputTypeId,
  type ProjectResponse,
  type SourceResponse,
  type TransformationJobResponse,
  projectsApi,
  sourcesApi,
  configurationsApi,
  contentIntelligenceApi,
  transformationsApi,
  errorMessage,
  ApiError,
} from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import {
  isTerminalJobStatus,
  outputTypeShortLabel,
  timeAgo,
} from "@/lib/outputTypes";
import {
  ensureQuickProject,
  isQuickProjectName,
} from "@/lib/quickWorkspace";
import { cn } from "@/lib/utils";
import {
  Plus,
  Mic,
  Send,
  Loader2,
  X,
  FileText,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Info,
} from "lucide-react";
import { ToneSelector, type Tone } from "@/components/configuration";
import { AudienceSelector } from "@/components/configuration";
import { LanguageSelector } from "@/components/configuration";
import { OutputSelector } from "@/components/output-selection";
import { TransformationProgress, PipelineStageTrack } from "@/components/results";
import { UnifiedResults } from "@/components/results";
import { StatusBadge, LoadingSpinner } from "@/components/common";

interface HomeWorkspaceProps {
  /** Polling interval for job status (default 2000ms). */
  pollIntervalMs?: number;
}

type Phase =
  | "loading"
  | "idle"
  | "processing"
  | "generating"
  | "completed"
  | "failed";

export function HomeWorkspace({ pollIntervalMs = 2000 }: HomeWorkspaceProps) {
  // ---- Environment (quick project) --------------------------------------
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [quickProjectId, setQuickProjectId] = useState<string | null>(null);

  // ---- Composer inputs ---------------------------------------------------
  const [prompt, setPrompt] = useState("");
  const [source, setSource] = useState<SourceResponse | null>(null);
  const [sourceUploading, setSourceUploading] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- Tone / audience / language ---------------------------------------
  const [tone, setTone] = useState<Tone>("Professional");
  const [audience, setAudience] = useState<string>("General");
  const [language, setLanguage] = useState<string>("English");

  // ---- Outputs -----------------------------------------------------------
  const [selectedOutputs, setSelectedOutputs] = useState<OutputTypeId[]>([]);
  const [configuration, setConfiguration] =
    useState<ConfigurationResponse | null>(null);

  // ---- Submission / progress ---------------------------------------------
  const [job, setJob] = useState<TransformationJobResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputResponse[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pollErrorMsg, setPollErrorMsg] = useState<string | null>(null);

  // ---- Recent items ------------------------------------------------------
  const [recentTransformations, setRecentTransformations] = useState<
    TransformationJobResponse[]
  >([]);
  const [recentProjects, setRecentProjects] = useState<ProjectResponse[]>([]);

  const [phase, setPhase] = useState<Phase>("loading");

  // -------------------------------------------------------------------------
  // Boot: ensure quick project + load recent activity
  // -------------------------------------------------------------------------
  const loadRecent = useCallback(async (quickProjectId: string) => {
    try {
      const [projRes, quickHistoryRes] = await Promise.all([
        projectsApi.list(),
        transformationsApi.listByProject(quickProjectId),
      ]);
      setRecentProjects(projRes.data.slice(0, 5));
      // recent transformations = quick project history (newest first, top 5)
      setRecentTransformations(quickHistoryRes.data.slice(0, 5));
    } catch {
      // non-fatal — recent lists simply stay empty
    }
  }, []);

  const boot = useCallback(async () => {
    setPhase("loading");
    try {
      const quick = await ensureQuickProject();
      setProject(quick);
      setQuickProjectId(quick.id);

      // Preload the quick project's latest source/config to hydrate the form.
      const [sourcesRes, configsRes] = await Promise.all([
        sourcesApi.list(quick.id),
        configurationsApi.list(quick.id),
      ]);
      if (sourcesRes.data.length > 0) setSource(sourcesRes.data[0]);
      if (configsRes.data.length > 0) setConfiguration(configsRes.data[0]);

      await loadRecent(quick.id);
      setPhase("idle");
    } catch (err) {
      setFormError(
        errorMessage(err, "We couldn't load your workspace. Please try again."),
      );
      setPhase("idle");
    }
  }, [loadRecent]);

  useEffect(() => {
    void boot();
  }, [boot]);

  // -------------------------------------------------------------------------
  // Source upload
  // -------------------------------------------------------------------------
  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || !quickProjectId || sourceUploading) return;
    const file = files[0];
    setSourceUploading(true);
    setSourceError(null);
    try {
      const res = await sourcesApi.ingestFile(quickProjectId, file);
      // Poll until ready (processing → ready/failed)
      const s = await waitForReady(res.data.id);
      setSource(s);
      setConfiguration(null); // new source → fresh config
    } catch (err) {
      setSourceError(
        errorMessage(err, "We couldn't process this source. Please try again."),
      );
    } finally {
      setSourceUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const waitForReady = useCallback(
    (sourceId: string): Promise<SourceResponse> =>
      new Promise((resolve, reject) => {
        const deadline = Date.now() + 120000;
        const tick = async () => {
          try {
            const res = await sourcesApi.get(sourceId);
            if (res.data.status === "ready") {
              // Kick off content intelligence so transformation can proceed.
              void contentIntelligenceApi.analyze(sourceId).catch(() => undefined);
              resolve(res.data);
            } else if (res.data.status === "failed") {
              reject(new ApiError(0, "This source could not be processed."));
            } else if (Date.now() > deadline) {
              reject(new ApiError(0, "Source processing is taking too long."));
            } else {
              setTimeout(tick, 1200);
            }
          } catch (err) {
            reject(err);
          }
        };
        void tick();
      }),
    [],
  );

  // -------------------------------------------------------------------------
  // Configuration + submission
  // -------------------------------------------------------------------------
  const ensureConfig = useCallback(async (): Promise<ConfigurationResponse | null> => {
    if (!quickProjectId) return null;
    if (configuration) return configuration;
    try {
      const res = await configurationsApi.create(quickProjectId, {
        target_audience: audience === "General" ? null : audience,
        tone: tone === "Professional" ? null : tone,
        language,
        detail_level: "standard",
        communication_objective: null,
      });
      setConfiguration(res.data);
      return res.data;
    } catch {
      return null;
    }
  }, [quickProjectId, configuration, audience, tone, language]);

  const sourceReady = source?.status === "ready";

  const hasInput = (prompt.trim().length > 0 || sourceReady) && selectedOutputs.length > 0;

  const canRun =
    phase !== "generating" &&
    phase !== "processing" &&
    phase !== "loading" &&
    hasInput;

  const handleRun = async () => {
    if (!canRun || !quickProjectId) return;
    setFormError(null);
    setPollErrorMsg(null);
    setOutputs([]);
    setPhase("generating");

    const cfg = configuration ?? (await ensureConfig());
    if (!cfg) {
      setFormError("We couldn't save your configuration. Please try again.");
      setPhase("idle");
      return;
    }

    // Phase 15 flexible inputs: prompt-only, source-only, or both. At least one
    // of prompt / source_id is provided (backend enforces the same rule).
    const payload = {
      project_id: quickProjectId,
      configuration_id: cfg.id,
      output_types: selectedOutputs,
      ...(prompt.trim() ? { prompt: prompt.trim() } : {}),
      ...(source ? { source_id: source.id } : {}),
    };

    try {
      const res = await transformationsApi.create(payload);
      setJob(res.data);
      setPhase("generating");
    } catch (err) {
      setFormError(
        errorMessage(err, "The transformation could not be started."),
      );
      setPhase("idle");
    }
  };

  // Clear config when tone/audience/language change so it re-persists.
  const handleToneChange = (t: Tone) => {
    setTone(t);
    setConfiguration(null);
  };
  const handleAudienceChange = (a: string | null) => {
    setAudience(a ?? "General");
    setConfiguration(null);
  };
  const handleLanguageChange = (l: string | null) => {
    setLanguage(l ?? "English");
    setConfiguration(null);
  };

  // -------------------------------------------------------------------------
  // Polling
  // -------------------------------------------------------------------------
  const refreshOutputs = useCallback(async (jobId: string) => {
    setOutputsLoading(true);
    try {
      const res = await transformationsApi.listOutputs(jobId);
      setOutputs(res.data);
    } catch {
      // keep existing outputs
    } finally {
      setOutputsLoading(false);
    }
  }, []);

  const pollEnabled = job !== null && !isTerminalJobStatus(job.status);

  const { data: polledJob } = usePolling({
    fetcher: async () => {
      const res = await transformationsApi.get(job!.id);
      return res.data;
    },
    isDone: (j) => isTerminalJobStatus(j.status),
    intervalMs: pollIntervalMs,
    enabled: pollEnabled,
    resetKey: job?.id,
    onError: () => {
      setPollErrorMsg("We lost track of your transformation. Please refresh.");
    },
    onDone: (j) => {
      void refreshOutputs(j.id);
      void loadRecent(quickProjectId ?? "");
    },
  });

  useEffect(() => {
    if (polledJob) {
      setJob(polledJob);
      if (isTerminalJobStatus(polledJob.status)) {
        setPhase(polledJob.status === "completed" ? "completed" : "failed");
      }
    }
  }, [polledJob]);

  const phaseLabel = (() => {
    switch (phase) {
      case "loading":
        return "Loading…";
      case "processing":
        return "Processing source…";
      case "generating":
        return "Transforming…";
      case "completed":
        return "Completed";
      case "failed":
        return "Failed";
      default:
        return "Ready";
    }
  })();

  if (phase === "loading") {
    return (
      <div className="py-24">
        <LoadingSpinner size="lg" label="Loading your workspace…" />
      </div>
    );
  }

  const running = (job && !isTerminalJobStatus(job.status)) || sourceUploading;

  return (
    <div className="mx-auto w-full max-w-3xl space-y-8">
      {/* Hero */}
      <section className="space-y-2 text-center">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground sm:text-3xl">
          What would you like to transform?
        </h2>
        <p className="mx-auto max-w-xl text-sm text-muted-foreground">
          Give TransformIQ your source and instructions. Choose one or more
          outputs and we&apos;ll transform them together.
        </p>
      </section>

      {/* Mandate */}
      <section className="space-y-2">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold text-foreground">Mandate</h3>
          <p className="text-xs text-muted-foreground">
            Describe what you want TransformIQ to create. A source is optional
            — the instruction alone is enough to transform.
          </p>
        </div>

        <div className="rounded-xl border border-border bg-surface-elevated shadow-sm">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Describe what you want TransformIQ to create…"
            rows={4}
            aria-label="Transformation prompt"
            className="w-full resize-y rounded-t-xl border-0 bg-transparent px-5 py-4 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none"
          />

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2.5">
            <div className="flex items-center gap-1">
              <input
                ref={fileInputRef}
                type="file"
                accept=".txt,.pdf,.docx"
                className="sr-only"
                aria-label="Upload source file"
                onChange={(e) => void handleFiles(e.target.files)}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={running}
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                Add source
              </button>
              <button
                type="button"
                disabled
                title="Voice input is not available yet"
                aria-label="Voice input is not available yet"
                aria-disabled="true"
                className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground/50 transition-colors"
              >
                <Mic className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>

            <button
              type="button"
              onClick={() => void handleRun()}
              disabled={!canRun}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              aria-label="Start transformation"
            >
              {phase === "generating" ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Sparkles className="h-4 w-4" aria-hidden="true" />
              )}
              Run
            </button>
          </div>
        </div>
      </section>

      {/* Source */}
      <section className="space-y-2">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold text-foreground">Source</h3>
          <p className="text-xs text-muted-foreground">
            Attach the material to transform. TransformIQ ingests and analyzes
            it before transforming.
          </p>
        </div>

        <div>
          {sourceUploading ? (
            <SourceChipUploading />
          ) : source ? (
            <SourceChip
              source={source}
              onRemove={() => {
                setSource(null);
                setConfiguration(null);
              }}
            />
          ) : (
            <p className="text-xs text-muted-foreground">
              No source attached — a prompt alone is enough to transform.
            </p>
          )}
          {sourceError && (
            <p role="alert" className="mt-1 text-xs font-medium text-destructive">
              {sourceError}
            </p>
          )}
        </div>
      </section>

      {/* Tone */}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Tone</h3>
        <ToneSelector value={tone} onChange={handleToneChange} disabled={running} />
      </section>

      {/* Audience */}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">Audience</h3>
        <AudienceSelector
          value={audience}
          onChange={handleAudienceChange}
          disabled={running}
        />
      </section>

      {/* Language */}
      <section className="space-y-2">
        <h3 className="text-sm font-semibold text-foreground">
          Output language
        </h3>
        <p className="text-xs text-muted-foreground">
          Write the outputs in this language.
        </p>
        <LanguageSelector
          value={language}
          onChange={handleLanguageChange}
          disabled={running}
        />
      </section>

      {/* Deliverables */}
      <section className="space-y-2">
        <div className="space-y-0.5">
          <h3 className="text-sm font-semibold text-foreground">
            Deliverables
          </h3>
          <p className="text-xs text-muted-foreground">
            Select one or more output formats. TransformIQ will create them
            from the same source and instructions.
          </p>
        </div>
        <OutputSelector
          selected={selectedOutputs}
          onChange={setSelectedOutputs}
          disabled={running}
        />
      </section>

      {/* Orchestration summary */}
      {selectedOutputs.length > 0 && (
        <section className="rounded-lg border border-primary/20 bg-primary/5 p-4">
          <p className="text-sm font-medium text-foreground">
            {selectedOutputs.length} output{selectedOutputs.length !== 1 ? "s" : ""}{" "}
            selected
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            TransformIQ will generate:
          </p>
          <ul className="mt-2 space-y-1">
            {selectedOutputs.map((id) => (
              <li key={id} className="flex items-center gap-2 text-sm text-foreground">
                <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
                {outputTypeShortLabel(id)}
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-muted-foreground">
            from{" "}
            {prompt.trim() && sourceReady
              ? "your source and instruction"
              : prompt.trim()
                ? "your instruction (no source attached)"
                : "your source (no additional instruction)"}
            . Outputs will be written in{" "}
            {language || "English"}.
          </p>
        </section>
      )}

      <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2.5 text-xs text-muted-foreground">
        <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
        Every deliverable is grounded in your source with inline citations, so
        you can trace each claim back to the originating content before using
        it.
      </p>

      {formError && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {formError}
        </p>
      )}

      {/* Run CTA */}
      <div className="flex flex-col items-center gap-2">
        <button
          type="button"
          onClick={() => void handleRun()}
          disabled={!canRun}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-primary-foreground shadow-[0_0_18px_rgba(37,99,235,0.25)] transition-all hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
        >
          {phase === "generating" ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          Transform
        </button>
        {!canRun && (
          <ul className="space-y-0.5 text-center text-xs text-muted-foreground">
            {!source && !prompt.trim() && (
              <li>• Describe what to create and/or attach a source</li>
            )}
            {source && !sourceReady && <li>• Wait for the source to become ready</li>}
            {selectedOutputs.length === 0 && (
              <li>• Choose one or more output formats to get started</li>
            )}
          </ul>
        )}
      </div>

      {/* Progress + results */}
      {job && (
        <section className="space-y-4">
          <div className="rounded-xl border border-border bg-surface-elevated p-5">
            <span className="label-mono-sm mb-4 block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Execution pipeline
            </span>
            <PipelineStageTrack job={job} outputs={outputs} />
          </div>
          <TransformationProgress job={job} outputs={outputs} />
          {isTerminalJobStatus(job.status) && (
            <UnifiedResults job={job} outputs={outputs} loading={outputsLoading} />
          )}
          {pollErrorMsg && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {pollErrorMsg}
            </p>
          )}
        </section>
      )}

      {/* Status label */}
      <div className="flex items-center justify-center gap-2 pt-2">
        <span className="text-xs text-muted-foreground">Status</span>
        <StatusBadge
          variant={
            phase === "completed"
              ? "success"
              : phase === "failed"
                ? "error"
                : phase === "generating" || phase === "processing"
                  ? "info"
                  : "default"
          }
        >
          {phaseLabel}
        </StatusBadge>
      </div>

      {/* Recent transformations */}
      <RecentList title="Recent Transformations" jobs={recentTransformations} />

      {/* Recent projects */}
      <RecentProjectsList projects={recentProjects} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SourceChip({
  source,
  onRemove,
}: {
  source: SourceResponse;
  onRemove: () => void;
}) {
  const ready = source.status === "ready";
  const failed = source.status === "failed";
  const processing = source.status === "processing" || source.status === "uploaded";
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm">
      <FileText className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
      <span className="truncate text-foreground">
        {source.original_filename ?? "Pasted text source"}
      </span>
      {ready && (
        <>
          <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
          <span className="text-xs text-success">Ready</span>
        </>
      )}
      {processing && (
        <>
          <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
          <span className="text-xs text-muted-foreground">Processing…</span>
        </>
      )}
      {failed && (
        <>
          <AlertCircle className="h-4 w-4 text-destructive" aria-hidden="true" />
          <span className="text-xs text-destructive">Failed</span>
        </>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="ml-auto rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        aria-label="Remove source"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </button>
    </div>
  );
}

function SourceChipUploading() {
  return (
    <div className="flex items-center gap-2 rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm">
      <Loader2 className="h-4 w-4 animate-spin text-primary" aria-hidden="true" />
      <span className="text-muted-foreground">Uploading source…</span>
    </div>
  );
}

function RecentList({
  title,
  jobs,
}: {
  title: string;
  jobs: TransformationJobResponse[];
}) {
  if (jobs.length === 0) return null;
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <Link href="/history" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </Link>
      </div>
      <ul className="space-y-2">
        {jobs.slice(0, 3).map((job) => (
          <li key={job.id}>
            <Link
              href="/history"
              className={cn(
                "flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-elevated px-4 py-3 text-sm transition-colors hover:border-input",
              )}
            >
              <span className="flex items-center gap-2">
                <span className="text-foreground">
                  {outputTypeShortLabel(
                    ((
                      job.requested_outputs as { output_types?: string[] } | null
                    )?.output_types ?? ["output"])[0],
                  )}
                </span>
                <span className="text-muted-foreground">
                  {(
                    (job.requested_outputs as { output_types?: string[] } | null)
                      ?.output_types?.length ?? 0
                  ) > 0
                    ? `+${(job.requested_outputs as { output_types?: string[] }).output_types!.length}`
                    : ""}
                </span>
              </span>
              <span className="label-mono-sm text-muted-foreground">
                {timeAgo(job.created_at)}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

function RecentProjectsList({ projects }: { projects: ProjectResponse[] }) {
  if (projects.length === 0) return null;
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">Recent Projects</h3>
        <a href="/projects" className="text-xs text-muted-foreground hover:text-foreground">
          View all →
        </a>
      </div>
      <ul className="space-y-2">
        {projects.slice(0, 3).map((project) => (
          <li key={project.id}>
            <a
              href={`/projects/${project.id}`}
              className="flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-elevated px-4 py-3 text-sm transition-colors hover:border-input"
            >
              <span className="truncate text-foreground">
                {isQuickProjectName(project.name) ? "Quick Transformations" : project.name}
              </span>
              <span className="label-mono-sm shrink-0 text-muted-foreground">
                {timeAgo(project.updated_at)}
              </span>
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}
