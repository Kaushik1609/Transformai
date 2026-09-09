/**
 * TransformIQ — Transformation workspace (Phase 9).
 *
 * The end-to-end user journey for a single project:
 *   1. Create/select project (entry from /projects)
 *   2. Add a source (text or file)
 *   3. See source info + processing state + content intelligence
 *   4. Configure audience / tone / language / detail / objective
 *   5. Select output types
 *   6. Generate a transformation job
 *   7. Poll job status without blocking the UI
 *   8. View outputs
 *   9. View verification (including the pending Phase 8 state)
 *   10. Download available artifacts
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import {
  type ConfigurationResponse,
  type OutputResponse,
  type OutputTypeId,
  type ProjectResponse,
  type SourceResponse,
  type TransformationJobResponse,
  projectsApi,
  configurationsApi,
  sourcesApi,
  transformationsApi,
  errorMessage,
} from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import {
  OUTPUT_TYPES,
  isTerminalJobStatus,
  jobStatusVariant,
  outputTypeLabel,
} from "@/lib/outputTypes";
import {
  StatusBadge,
  ErrorState,
  EmptyState,
  LoadingSpinner,
  ProgressBar,
  SectionCard,
} from "@/components/common";
import { SourceUpload, CurrentSource } from "@/components/upload";
import { SourceAnalysis } from "./SourceAnalysis";
import { ConfigurationForm } from "@/components/configuration";
import { OutputSelector } from "@/components/output-selection";
import { ResultsPanel, PipelineStageTrack } from "@/components/results";
import { HistoryPanel } from "@/components/history";

interface TransformationWorkspaceProps {
  projectId: string;
  /** Polling interval for job status (default 2000ms; shorter in tests). */
  pollIntervalMs?: number;
}

type WorkspacePhase =
  | "loading"
  | "idle"
  | "processing"
  | "generating"
  | "verifying"
  | "completed"
  | "failed";

export function TransformationWorkspace({
  projectId,
  pollIntervalMs = 2000,
}: TransformationWorkspaceProps) {
  // ---- Project / sources / configs -------------------------------------
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [currentSource, setCurrentSource] = useState<SourceResponse | null>(
    null,
  );
  const [configuration, setConfiguration] =
    useState<ConfigurationResponse | null>(null);
  const [loading, setLoading] = useState(true);

  // ---- Generation ------------------------------------------------------
  const [selectedOutputs, setSelectedOutputs] = useState<OutputTypeId[]>([]);
  const [job, setJob] = useState<TransformationJobResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputResponse[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pollErrorMsg, setPollErrorMsg] = useState<string | null>(null);

  const loadWorkspace = useCallback(async () => {
    setProjectError(null);
    try {
      const [projectRes, sourcesRes, configsRes] = await Promise.all([
        projectsApi.get(projectId),
        sourcesApi.list(projectId),
        configurationsApi.list(projectId),
      ]);
      setProject(projectRes.data);
      const sourceList = sourcesRes.data;
      setSources(sourceList);
      setCurrentSource(sourceList[0] ?? null);
      if (configsRes.data.length > 0) {
        setConfiguration(configsRes.data[0]);
      }
    } catch (err) {
      setProjectError(
        errorMessage(err, "Failed to load the workspace."),
      );
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const refreshOutputs = useCallback(async (jobId: string) => {
    setOutputsLoading(true);
    try {
      const res = await transformationsApi.listOutputs(jobId);
      setOutputs(res.data);
    } catch {
      // outputs remain empty; the workspace error state communicates it
    } finally {
      setOutputsLoading(false);
    }
  }, []);

  // ---- Job polling (starts when a job exists, stops at a terminal state)
  const pollEnabled = job !== null && !isTerminalJobStatus(job.status);

  const { data: polledJob, phase: pollPhase, error: pollError } = usePolling({
    fetcher: async () => {
      const res = await transformationsApi.get(job!.id);
      return res.data;
    },
    isDone: (j) => isTerminalJobStatus(j.status),
    intervalMs: pollIntervalMs,
    enabled: pollEnabled,
    resetKey: job?.id,
    onError: (err) => {
      setPollErrorMsg(
        errorMessage(err, "Failed to monitor job progress."),
      );
    },
    onDone: (j) => {
      void refreshOutputs(j.id);
    },
  });

  // Keep the displayed job in sync with poll results (progress/status).
  useEffect(() => {
    if (polledJob) setJob(polledJob);
  }, [polledJob]);

  // Clear transient poll errors when a fresh job starts.
  useEffect(() => {
    setPollErrorMsg(null);
  }, [job?.id]);

  // ---- Derived phase ---------------------------------------------------
  const phase: WorkspacePhase = (() => {
    if (loading) return "loading";
    if (!currentSource) return "idle";
    if (
      currentSource.status === "processing" ||
      currentSource.status === "uploaded"
    )
      return "processing";
    if (job) {
      if (!isTerminalJobStatus(job.status)) return "generating";
      if (outputsLoading) return "verifying";
      if (job.status === "completed") return "completed";
      return "failed";
    }
    return "idle";
  })();

  const generationReady =
    !!currentSource &&
    currentSource.status === "ready" &&
    !!configuration &&
    selectedOutputs.length > 0;

  const canGenerate = generationReady && (!job || isTerminalJobStatus(job.status));

  const handleGenerate = async () => {
    if (!canGenerate || !currentSource || !configuration) return;
    setFormError(null);
    setOutputs([]);
    try {
      const res = await transformationsApi.create({
        project_id: projectId,
        source_id: currentSource.id,
        configuration_id: configuration.id,
        output_types: selectedOutputs,
      });
      setJob(res.data);
    } catch (err) {
      setFormError(
        errorMessage(err, "Failed to start generation."),
      );
    }
  };

  const handleSelectHistoricalJob = (historical: TransformationJobResponse) => {
    setPollErrorMsg(null);
    setFormError(null);
    setOutputs([]);
    setJob(historical);
    if (isTerminalJobStatus(historical.status)) {
      void refreshOutputs(historical.id);
    }
  };

  const handleSourceAdded = (source: SourceResponse) => {
    setSources((prev) => [source, ...prev]);
    setCurrentSource(source);
  };

  const statusLabel = (() => {
    switch (phase) {
      case "loading":
        return "Loading workspace…";
      case "processing":
        return "Processing source…";
      case "generating":
        return "Transforming…";
      case "verifying":
        return "Verifying outputs…";
      case "completed":
        return "Completed";
      case "failed":
        return "Failed";
      default:
        return "Idle";
    }
  })();

  // -----------------------------------------------------------------------
  if (loading) {
    return (
      <div className="py-16">
        <LoadingSpinner size="lg" label="Loading workspace…" />
      </div>
    );
  }

  if (projectError) {
    return (
      <ErrorState
        message={projectError}
        onRetry={() => {
          setLoading(true);
          void loadWorkspace();
        }}
      />
    );
  }

  const setupDisabled = !!job && !isTerminalJobStatus(job.status);

  return (
    <div className="space-y-6">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {project?.name ?? "Transformation workspace"}
          </h1>
          {project?.description && (
            <p className="text-sm text-muted-foreground">
              {project.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">
            Status
          </span>
          <StatusBadge variant={phaseBadgeVariant(phase)}>
            {statusLabel}
          </StatusBadge>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* ------------------------------------------------------ */}
        {/* Left column — setup                                     */}
        {/* ------------------------------------------------------ */}
        <div className="space-y-6">
          <SectionCard
            title="1 · Source"
            description="Upload the material to transform."
            right={
              currentSource && <StatusBadge variant="info">selected</StatusBadge>
            }
          >
            <div className="space-y-4">
              {currentSource ? (
                <>
                  <CurrentSource source={currentSource} />
                  {currentSource.status === "ready" && (
                    <SourceAnalysis source={currentSource} />
                  )}
                </>
              ) : (
                <EmptyState
                  title="No source yet"
                  description="Add a text block or upload a document to begin."
                />
              )}
              <SourceUpload
                projectId={projectId}
                onSourceAdded={handleSourceAdded}
                disabled={setupDisabled}
              />
            </div>
          </SectionCard>

          <SectionCard
            title="2 · Configuration"
            description="How should the outputs be written?"
            right={
              configuration && <StatusBadge variant="success">saved</StatusBadge>
            }
          >
            {configuration && (
              <div className="mb-3 rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
                Saved: audience “{configuration.target_audience || "—"}” · tone “
                {configuration.tone || "—"}” · language “
                {configuration.language}” · detail “
                {configuration.detail_level || "—"}” · objective “
                {configuration.communication_objective || "—"}”
              </div>
            )}
            <ConfigurationForm
              projectId={projectId}
              onConfigCreated={setConfiguration}
              disabled={setupDisabled}
            />
          </SectionCard>

<SectionCard
              title="3 · Outputs"
              description="Choose what to transform."
            right={
              selectedOutputs.length > 0 && (
                <StatusBadge variant="info">
                  {selectedOutputs.length} selected
                </StatusBadge>
              )
            }
          >
            <OutputSelector
              selected={selectedOutputs}
              onChange={setSelectedOutputs}
              disabled={setupDisabled}
            />
          </SectionCard>
        </div>

        {/* ------------------------------------------------------ */}
        {/* Right column — run / results                            */}
        {/* ------------------------------------------------------ */}
        <div className="space-y-6">
          <SectionCard
            title="4 · Transform"
            description="Start an asynchronous transformation job."
          >
            <div className="space-y-4">
              <button
                type="button"
                onClick={() => void handleGenerate()}
                disabled={!canGenerate}
                className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {phase === "generating" ? (
                  <>
                    <LoadingSpinner size="sm" label="Transforming…" />
                    Transforming…
                  </>
                ) : (
                  "Transform"
                )}
              </button>

              {!generationReady && !formError && !pollErrorMsg && (
                <ul className="space-y-1 text-xs text-muted-foreground">
                  {!currentSource && <li>• Add a source first</li>}
                  {currentSource && currentSource.status !== "ready" && (
                    <li>• Wait for the source to become ready</li>
                  )}
                  {!configuration && <li>• Save a configuration</li>}
                  {selectedOutputs.length === 0 && (
                    <li>• Select at least one output type</li>
                  )}
                </ul>
              )}

              {formError && (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {formError}
                </p>
              )}
              {pollErrorMsg && (
                <p role="alert" className="text-xs font-medium text-destructive">
                  {pollErrorMsg}
                </p>
              )}
              {pollPhase === "error" && !!pollError && (
                <ErrorState message="Failed to monitor job progress." />
              )}

              {job && <JobProgress job={job} outputs={outputs} />}
            </div>
          </SectionCard>

          {job && (
            <SectionCard
              title="5 · Results & verification"
              description="Transformed artifacts and their verification state."
            >
              <div className="space-y-3">
                {job.status === "failed" && job.error_message && (
                  <ErrorState message={job.error_message} />
                )}
                {job.status === "cancelled" && (
                  <p className="text-xs text-muted-foreground">
                    This job was cancelled.
                  </p>
                )}
                <ResultsPanel outputs={outputs} loading={outputsLoading} />
              </div>
            </SectionCard>
          )}

          {!job && (
            <p className="hidden text-xs text-muted-foreground lg:block">
              Results and verification will appear here after you transform.
            </p>
          )}

          <SectionCard
            title="6 · History"
            description="Past transformation jobs for this project."
          >
            <HistoryPanel
              projectId={projectId}
              currentJobId={job?.id}
              outputsByJobId={
                job ? { [job.id]: outputs } : undefined
              }
              onSelectJob={handleSelectHistoricalJob}
            />
          </SectionCard>
        </div>
      </div>
    </div>
  );
}

function phaseBadgeVariant(
  phase: WorkspacePhase,
): "default" | "success" | "warning" | "error" | "info" | "muted" {
  switch (phase) {
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "processing":
    case "generating":
    case "verifying":
    case "loading":
      return "info";
    default:
      return "default";
  }
}

function JobProgress({
  job,
  outputs,
}: {
  job: TransformationJobResponse;
  outputs: OutputResponse[];
}) {
  const running = !isTerminalJobStatus(job.status);
  const determinate = job.status === "completed" || job.status === "failed";

  const requested = (
    (job.requested_outputs as { output_types?: string[] } | null)
      ?.output_types ?? []
  )
    .map((t) => outputTypeLabel(t))
    .join(", ");

  return (
    <div className="space-y-2 rounded-md border border-border bg-muted/20 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="label-mono-sm flex items-center gap-2 font-medium text-foreground">
          Job {job.id.slice(0, 8)}…
          <StatusBadge variant={jobStatusVariant(job.status)}>
            {job.status}
          </StatusBadge>
        </span>
        <span className="label-mono-sm text-muted-foreground">
          {running ? "In progress…" : `${job.progress}%`}
        </span>
      </div>

      <ProgressBar
        value={determinate ? job.progress : null}
        label="Job progress"
      />

      <PipelineStageTrack job={job} outputs={outputs} className="pt-1" />

      {running && (
        <p className="text-xs text-muted-foreground">
          Requested:
          {requested ? ` ${requested}` : " outputs"}
        </p>
      )}

      {outputs.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {outputs.map((o) => (
            <li key={o.id}>
              {outputTypeLabel(o.output_type)} · {o.status}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}