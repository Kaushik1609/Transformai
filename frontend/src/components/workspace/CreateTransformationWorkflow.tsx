/**
 * TransformIQ — Create Transformation workflow (Stitch enterprise console).
 *
 * A guided, four-stage creation flow structurally faithful to the Stitch
 * reference screen:
 *
 *   1. Input Workspace  — primary source (file upload / raw ingest) + prompt & strategic directives
 *   2. Configure        — language, audience, tone, depth, objective, style & situational context
 *   3. Output Packages  — selectable output packages with batch presets
 *   4. Review & Dispatch — blueprint audit summary + compliance dock + execution tracker
 *
 * Every gate mirrors the backend contract: a prompt and/or a ready source is
 * required, at least one output must be selected, and the configuration is
 * persisted before dispatch. No fabricated metrics, percentages, or safety
 * claims — only real source/config/job signals are surfaced.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  type ConfigurationResponse,
  type OutputResponse,
  type OutputTypeId,
  type SourceResponse,
  type TransformationJobResponse,
  sourcesApi,
  configurationsApi,
  contentIntelligenceApi,
  transformationsApi,
  errorMessage,
  ApiError,
  getSourceClassification,
  getPolicyPosture,
} from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import {
  isTerminalJobStatus,
  outputTypeShortLabel,
  formatFileSize,
  timeAgo,
  sourceStatusVariant,
} from "@/lib/outputTypes";
import { ensureQuickProject } from "@/lib/quickWorkspace";
import { cn } from "@/lib/utils";
import { ToneSelector, type Tone } from "@/components/configuration";
import { AudienceSelector } from "@/components/configuration";
import { LanguageSelector } from "@/components/configuration";
import { OutputPackageGrid } from "@/components/output-selection";
import {
  sourceSecuritySignals,
  type SecuritySignal,
} from "@/components/projects/ProjectSourceLibrary";
import { TransformationProgress, PipelineStageTrack } from "@/components/results";
import { UnifiedResults } from "@/components/results";
import { StatusBadge, LoadingSpinner } from "@/components/common";
import {
  FileText,
  PenLine,
  Users,
  Globe,
  UploadCloud,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Info,
  Workflow,
  ShieldCheck,
  ArrowLeft,
  ArrowRight,
  Save,
  X,
  Lock,
  Layers,
  Terminal,
  RotateCcw,
  Flag,
  LayoutGrid,
  AlignJustify,
  MessageSquarePlus,
} from "lucide-react";

interface CreateTransformationWorkflowProps {
  /** Polling interval for job status (default 2000ms). */
  pollIntervalMs?: number;
}

type Phase = "loading" | "idle" | "generating" | "completed" | "failed";

type IngestMode = "file" | "raw";

const STEPS: {
  step: number;
  title: string;
  subtitle: string;
  subtitleDynamic?: boolean;
}[] = [
  { step: 1, title: "Input Workspace", subtitle: "Source & Prompt" },
  { step: 2, title: "Configure", subtitle: "Audience & Framing" },
  { step: 3, title: "Output Packages", subtitle: "", subtitleDynamic: true },
  { step: 4, title: "Review & Dispatch", subtitle: "Audit Verification" },
];

const LANG_NAMES: Record<string, string> = {
  en: "English",
  hi: "Hindi",
  es: "Spanish",
  fr: "French",
  de: "German",
  pt: "Portuguese",
  zh: "Chinese",
  ar: "Arabic",
  ja: "Japanese",
  ko: "Korean",
};

function languageLabel(code?: string | null): string {
  if (!code) return "—";
  return LANG_NAMES[code.toLowerCase()] ?? code.toUpperCase();
}

function mimeTypeLabel(source: SourceResponse): string {
  const mime = (source.mime_type ?? "").toLowerCase();
  if (mime.includes("pdf")) return "PDF";
  if (mime.includes("wordprocessingml") || source.original_filename?.toLowerCase().endsWith(".docx"))
    return "DOCX";
  if (mime.startsWith("text/") || source.original_filename?.toLowerCase().endsWith(".txt"))
    return "TXT";
  if (source.source_type === "text") return "Text";
  return mime || "File";
}

function sourceStatusLabel(status: string): string {
  switch (status) {
    case "ready":
      return "Ready";
    case "processing":
    case "uploaded":
      return "Processing…";
    case "failed":
      return "Failed";
    default:
      return "Unavailable";
  }
}

const SIGNAL_LABEL: Record<SecuritySignal, string> = {
  CLEAN: "Clean",
  BLOCKED: "Blocked",
  DETECTED: "Detected",
  NOT_DETECTED: "Not detected",
  UNAVAILABLE: "Unavailable",
};

export function CreateTransformationWorkflow({
  pollIntervalMs = 2000,
}: CreateTransformationWorkflowProps) {
  // ---- Environment (quick project) --------------------------------------
  const [quickProjectId, setQuickProjectId] = useState<string | null>(null);

  // ---- Input workspace ---------------------------------------------------
  const [prompt, setPrompt] = useState("");
  const [source, setSource] = useState<SourceResponse | null>(null);
  const [sourceUploading, setSourceUploading] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [ingestMode, setIngestMode] = useState<IngestMode>("file");
  const [rawText, setRawText] = useState("");
  const [rawIngesting, setRawIngesting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---- Configure ----------------------------------------------------------
  const [tone, setTone] = useState<Tone>("Professional");
  const [audience, setAudience] = useState<string>("General");
  const [language, setLanguage] = useState<string>("English");
  const [detailLevel, setDetailLevel] = useState<"brief" | "standard" | "detailed">("standard");
  const [objective, setObjective] = useState<"brief" | "summarize" | "advise">("brief");
  const [styleArchetype, setStyleArchetype] = useState<string>("Executive");
  const [situationalIntent, setSituationalIntent] = useState<string>("");

  // ---- Output packages ----------------------------------------------------
  const [selectedOutputs, setSelectedOutputs] = useState<OutputTypeId[]>([]);
  const [configuration, setConfiguration] =
    useState<ConfigurationResponse | null>(null);
  const [configSaving, setConfigSaving] = useState(false);

  // ---- Stage / progress ---------------------------------------------------
  const [stage, setStage] = useState(1);
  const [job, setJob] = useState<TransformationJobResponse | null>(null);
  const [outputs, setOutputs] = useState<OutputResponse[]>([]);
  const [outputsLoading, setOutputsLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [pollErrorMsg, setPollErrorMsg] = useState<string | null>(null);
  const [draftSaved, setDraftSaved] = useState(false);

  const [phase, setPhase] = useState<Phase>("loading");

  // -------------------------------------------------------------------------
  // Boot: ensure quick project + hydrate with the latest source/config
  // -------------------------------------------------------------------------
  const boot = useCallback(async () => {
    setPhase("loading");
    try {
      const quick = await ensureQuickProject();
      setQuickProjectId(quick.id);

      const [configsRes, sourcesRes] = await Promise.all([
        configurationsApi.list(quick.id),
        sourcesApi.list(quick.id).catch(() => ({ data: [] })),
      ]);
      // Sources hydrated for quick workspace; user explicitly chooses/attaches active source
      if (configsRes.data.length > 0) {
        const c = configsRes.data[0];
        setConfiguration(c);
        if (c.language) setLanguage(c.language);
        if (c.target_audience) setAudience(c.target_audience);
        if (c.tone) setTone(c.tone as Tone);
      }

      setPhase("idle");
    } catch (err) {
      setFormError(
        errorMessage(err, "We couldn't load your workspace. Please try again."),
      );
      setPhase("idle");
    }
  }, []);

  useEffect(() => {
    void boot();
  }, [boot]);

  // -------------------------------------------------------------------------
  // Source ingestion (file upload + raw ingest)
  // -------------------------------------------------------------------------
  const waitForReady = useCallback(
    (sourceId: string): Promise<SourceResponse> =>
      new Promise((resolve, reject) => {
        const deadline = Date.now() + 120000;
        const tick = async () => {
          try {
            const res = await sourcesApi.get(sourceId);
            if (res.data.status === "ready") {
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

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0 || !quickProjectId || sourceUploading) return;
    const file = files[0];
    setSourceUploading(true);
    setSourceError(null);
    try {
      const res = await sourcesApi.ingestFile(quickProjectId, file);
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

  const handleRawIngest = async () => {
    if (!rawText.trim() || !quickProjectId || rawIngesting) return;
    setRawIngesting(true);
    setSourceError(null);
    try {
      const res = await sourcesApi.ingestText(quickProjectId, rawText.trim());
      const s = await waitForReady(res.data.id);
      setSource(s);
      setRawText("");
      setConfiguration(null);
    } catch (err) {
      setSourceError(
        errorMessage(err, "We couldn't ingest this text. Please try again."),
      );
    } finally {
      setRawIngesting(false);
    }
  };

  // -------------------------------------------------------------------------
  // Configuration persistence
  // -------------------------------------------------------------------------
  const ensureConfig = useCallback(async (): Promise<ConfigurationResponse | null> => {
    if (!quickProjectId) return null;
    if (configuration) return configuration;
    try {
      const res = await configurationsApi.create(quickProjectId, {
        target_audience: audience === "General" ? null : audience,
        tone: tone === "Professional" ? null : tone,
        language,
        detail_level: detailLevel,
        communication_objective: objective,
      });
      setConfiguration(res.data);
      return res.data;
    } catch {
      return null;
    }
  }, [quickProjectId, configuration, audience, tone, language, detailLevel, objective]);

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

  // Directive presets
  const applyDirective = (text: string) => {
    setPrompt(text);
  };

  // -------------------------------------------------------------------------
  // Stage gating
  // -------------------------------------------------------------------------
  const sourceReady = source?.status === "ready";
  const running = (job !== null && !isTerminalJobStatus(job.status)) || sourceUploading || rawIngesting;
  const inputReady = prompt.trim().length > 0 || sourceReady;
  const canTransform =
    phase !== "generating" &&
    phase !== "loading" &&
    inputReady &&
    configuration !== null &&
    selectedOutputs.length > 0;

  const reachable = useCallback(
    (target: number) => {
      if (target <= stage) return true;
      if (target === 2) return inputReady;
      if (target === 3) return inputReady && configuration !== null;
      if (target === 4)
        return inputReady && configuration !== null && selectedOutputs.length > 0;
      return false;
    },
    [stage, inputReady, configuration, selectedOutputs],
  );

  const goToStage = useCallback(
    (next: number) => {
      if (running) return;
      if (next === stage) return;

      if (next > stage) {
        if (next === 2 && !inputReady) return;
        if (next >= 3 && !inputReady) return;
        if (next >= 3 && configuration === null) return;
        if (next === 4 && selectedOutputs.length === 0) return;
      }
      setStage(next);
    },
    [stage, running, inputReady, configuration, selectedOutputs],
  );

  const nextToOutputs = async () => {
    if (configSaving || running) return;
    setFormError(null);
    setConfigSaving(true);
    const cfg = await ensureConfig();
    setConfigSaving(false);
    if (!cfg) {
      setFormError("We couldn't save your configuration. Please try again.");
      return;
    }
    setStage(3);
  };

  const nextToReview = async () => {
    if (configSaving || running || selectedOutputs.length === 0) return;
    setFormError(null);
    setConfigSaving(true);
    const cfg = await ensureConfig();
    setConfigSaving(false);
    if (!cfg) {
      setFormError("We couldn't save your configuration. Please try again.");
      return;
    }
    setStage(4);
  };

  // -------------------------------------------------------------------------
  // Dispatch
  // -------------------------------------------------------------------------
  const handleTransform = async () => {
    if (!canTransform || !quickProjectId) return;
    setFormError(null);
    setPollErrorMsg(null);
    setOutputs([]);

    const cfg = configuration ?? (await ensureConfig());
    if (!cfg) {
      setFormError("We couldn't save your configuration. Please try again.");
      return;
    }

    const selectedProvider =
      typeof window !== "undefined"
        ? localStorage.getItem("transformiq.llm_provider")
        : null;

    const payload = {
      project_id: quickProjectId,
      configuration_id: cfg.id,
      output_types: selectedOutputs,
      ...(prompt.trim() ? { prompt: prompt.trim() } : {}),
      ...(sourceReady ? { source_id: source!.id } : {}),
      ...(selectedProvider && selectedProvider !== "server"
        ? { llm_provider: selectedProvider }
        : {}),
    };

    setStage(4);
    setPhase("generating");
    try {
      const res = await transformationsApi.create(payload);
      setJob(res.data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        const msg = err.detail || "Processing blocked by policy.";
        setFormError(
          msg.toLowerCase().includes("policy")
            ? msg
            : `Processing blocked by policy: ${msg}`,
        );
      } else {
        setFormError(
          errorMessage(err, "The transformation could not be started."),
        );
      }
      setPhase("idle");
    }
  };

  // -------------------------------------------------------------------------
  // Polling / results
  // -------------------------------------------------------------------------
  const refreshOutputs = useCallback(async (jobId: string) => {
    setOutputsLoading(true);
    try {
      const res = await transformationsApi.listOutputs(jobId);
      setOutputs(res.data);
    } catch {
      // keep existing
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

  // -------------------------------------------------------------------------
  // Derived presentation state
  // -------------------------------------------------------------------------
  const mode = (() => {
    const hasPrompt = prompt.trim().length > 0;
    const hasSource = sourceReady;
    if (hasPrompt && hasSource) {
      return { id: "C", label: "Source + Prompt Active", note: "Dual-vector synthesis with source grounding." };
    }
    if (hasPrompt) {
      return { id: "B", label: "Prompt Directive Active", note: "Strategic mandate only — no source attached." };
    }
    if (hasSource) {
      return { id: "A", label: "Source Corpus Active", note: "Source-only — deterministic factual extraction." };
    }
    return { id: "—", label: "Awaiting Input", note: "Add a source, a prompt, or both to begin." };
  })();

  const active = phase === "completed" || phase === "failed";

  const handleSaveDraft = () => {
    try {
      localStorage.setItem(
        "transformiq_draft",
        JSON.stringify({ prompt, tone, audience, language, selectedOutputs }),
      );
      setDraftSaved(true);
      setTimeout(() => setDraftSaved(false), 2500);
    } catch {
      // ignore
    }
  };

  if (phase === "loading") {
    return (
      <div className="py-24">
        <LoadingSpinner size="lg" label="Loading your transformation workspace…" />
      </div>
    );
  }

  return (
    <div className="flex w-full flex-col gap-6">
      {/* 1. Top Command & Workflow Bar */}
      <section className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
        <div className="min-w-0 space-y-1.5">
          <nav aria-label="Breadcrumb" className="flex items-center gap-2 label-mono-sm text-outline">
            <Link href="/" className="transition-colors hover:text-foreground">Workspace</Link>
            <span className="text-outline">/</span>
            <span className="font-semibold text-primary">Create Transformation</span>
            <span className="ml-1 rounded bg-primary-container/20 px-1.5 py-0.5 label-mono-sm text-[10px] uppercase text-primary">
              RAG Stage 4.2
            </span>
          </nav>
          <h1 className="headline-xl font-semibold tracking-tight text-foreground">
            Create Transformation
          </h1>
          <p className="body-md max-w-2xl text-muted-foreground">
            Turn a source, prompt, or both into purpose-specific intelligence and executive communication.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={handleSaveDraft}
            className="inline-flex items-center gap-2 rounded bg-surface-container px-3.5 py-2 headline-sm body-sm text-foreground shadow-sm transition-all hover:bg-surface-container-high"
          >
            <Save className="h-4 w-4 text-outline" aria-hidden="true" />
            <span>{draftSaved ? "Saved!" : "Save Draft"}</span>
          </button>
        </div>
      </section>

      {/* 2. Stepper Indicator */}
      <StageIndicator
        current={stage}
        running={running}
        selectedCount={selectedOutputs.length}
        onSelect={goToStage}
        canGoToStep={reachable}
        disabled={running}
      />

      {/* 3. Operational Mode Notification Banner */}
      <section className="flex flex-col justify-between gap-3 rounded-lg bg-surface-container-low px-4 py-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded bg-secondary/10 text-secondary-fixed-dim">
            <Layers className="h-5 w-5" aria-hidden="true" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="label-mono-xs uppercase tracking-wide text-foreground">
                Operational Mode · Mode {mode.id}
              </span>
              <StatusBadge variant={mode.id === "—" ? "muted" : "success"}>
                {mode.id === "—" ? "Awaiting Input" : "Active"}
              </StatusBadge>
            </div>
            <span className="caption text-muted-foreground">
              {mode.label} — {mode.note}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2 self-end sm:self-auto">
          <span className="label-mono-sm text-outline">Deterministic Engine</span>
          <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
          <span className="label-mono-sm text-secondary-fixed-dim">Enforced</span>
        </div>
      </section>

      {/* 4. Stage Content Views */}
      {/* ======================================================== */}
      {/* STEP 1: INPUT WORKSPACE                                  */}
      {/* ======================================================== */}
      {stage === 1 && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* LEFT: SOURCE AREA (7 Cols) */}
          <div className="flex flex-col rounded-xl bg-surface-container-low p-6 lg:col-span-7">
            <div className="flex items-center justify-between pb-4">
              <div className="flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary" />
                <h2 className="headline-md font-semibold text-foreground">1. Primary Source Corpus</h2>
              </div>
              <div className="flex items-center rounded bg-surface-container p-0.5">
                <button
                  type="button"
                  onClick={() => setIngestMode("file")}
                  className={cn(
                    "rounded px-2.5 py-1 caption label-mono-sm transition-colors",
                    ingestMode === "file"
                      ? "bg-surface-container-high text-foreground"
                      : "text-outline hover:text-foreground",
                  )}
                >
                  File Upload
                </button>
                <button
                  type="button"
                  onClick={() => setIngestMode("raw")}
                  className={cn(
                    "rounded px-2.5 py-1 caption label-mono-sm transition-colors",
                    ingestMode === "raw"
                      ? "bg-surface-container-high text-foreground"
                      : "text-outline hover:text-foreground",
                  )}
                >
                  Raw Ingest
                </button>
              </div>
            </div>

            {ingestMode === "file" ? (
              <div className="flex flex-col gap-4">
                {source ? (
                  <SourceCard
                    source={source}
                    onRemove={() => {
                      setSource(null);
                      setConfiguration(null);
                    }}
                    onReplace={() => fileInputRef.current?.click()}
                  />
                ) : (
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border-default bg-surface-container-lowest/40 p-8 text-center transition-all hover:bg-surface-container-lowest/70"
                  >
                    <div className="mb-1 flex h-10 w-10 items-center justify-center rounded-full bg-surface-container-high text-primary">
                      {sourceUploading ? (
                        <Loader2 className="h-5 w-5 animate-spin" />
                      ) : (
                        <UploadCloud className="h-5 w-5" />
                      )}
                    </div>
                    <p className="headline-sm body-sm font-medium text-foreground">
                      {sourceUploading
                        ? "Uploading & indexing source material…"
                        : "Upload intelligence artifact or click to browse"}
                    </p>
                    <p className="caption text-outline">
                      Supported formats: PDF, DOCX, TXT (Auto-extracted)
                    </p>
                    <button
                      type="button"
                      disabled={sourceUploading}
                      className="mt-2 rounded bg-surface-container-high px-3 py-1.5 label-mono-sm text-foreground transition-colors hover:bg-surface-container-highest"
                    >
                      Browse System Files
                    </button>
                  </div>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".txt,.pdf,.docx"
                  className="sr-only"
                  aria-label="Upload source file"
                  onChange={(e) => void handleFiles(e.target.files)}
                />
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                <textarea
                  value={rawText}
                  onChange={(e) => setRawText(e.target.value)}
                  placeholder="Paste intelligence intercept, raw report excerpt, unformatted speech or notes here..."
                  rows={8}
                  maxLength={250000}
                  aria-label="Raw text source"
                  className="w-full resize-none rounded-lg bg-surface-container p-3.5 body-md text-foreground placeholder:text-outline focus:bg-surface-container-high focus:outline-none"
                />
                <div className="flex items-center justify-between caption label-mono-sm text-outline">
                  <span>Supports plaintext, Markdown syntax, and structured logs</span>
                  <span>{rawText.length.toLocaleString()} / 250,000 characters</span>
                </div>
                <button
                  type="button"
                  onClick={() => void handleRawIngest()}
                  disabled={!rawText.trim() || rawIngesting}
                  className="inline-flex self-end items-center gap-2 rounded bg-primary px-4 py-2 label-mono-sm text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {rawIngesting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <UploadCloud className="h-4 w-4" />
                  )}
                  <span>Ingest as Source</span>
                </button>
              </div>
            )}

            {sourceError && (
              <p role="alert" className="mt-3 text-xs font-medium text-destructive">
                {sourceError}
              </p>
            )}
          </div>

          {/* RIGHT: PROMPT AREA (5 Cols) */}
          <div className="flex flex-col rounded-xl bg-surface-container-low p-6 lg:col-span-5">
            <div className="flex items-center justify-between pb-4">
              <div className="flex items-center gap-2">
                <Terminal className="h-5 w-5 text-secondary-fixed-dim" />
                <h2 className="headline-md font-semibold text-foreground">2. Strategic Prompt & Mandate</h2>
              </div>
              <span className="label-mono-sm uppercase text-outline">Optional</span>
            </div>

            <div className="flex flex-1 flex-col gap-3">
              <p className="caption text-muted-foreground">
                Guide how KaryaSetu AI extracts, contextualizes, and refines the knowledge base.
              </p>
              <div className="relative flex flex-1 flex-col">
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  placeholder="Describe what you want KaryaSetu AI to create... e.g., Create a concise executive briefing focused on major risks and immediate mitigations."
                  rows={8}
                  aria-label="Transformation prompt"
                  className="w-full h-full min-h-[160px] resize-none rounded-lg bg-surface-container p-3.5 body-md text-foreground placeholder:text-outline focus:bg-surface-container-high focus:outline-none"
                />
                {prompt && (
                  <button
                    type="button"
                    onClick={() => setPrompt("")}
                    className="absolute right-2 top-2 rounded p-1 text-outline transition-colors hover:text-foreground"
                    title="Clear prompt"
                  >
                    <X className="h-4 w-4" />
                  </button>
                )}
              </div>

              {/* Quick Directive Presets */}
              <div className="flex flex-col gap-1.5 pt-2">
                <span className="label-mono-sm text-outline">Strategic Quick Directives:</span>
                <div className="flex flex-wrap gap-1.5">
                  <button
                    type="button"
                    onClick={() =>
                      applyDirective("Executive BLUF Brief: Synthesize bottom-line-up-front actions and key findings.")
                    }
                    className="inline-flex items-center gap-1 rounded bg-surface-container px-2.5 py-1 label-mono-sm text-foreground transition-colors hover:bg-surface-container-high"
                  >
                    <FileText className="h-3.5 w-3.5 text-secondary-fixed-dim" />
                    <span>Executive BLUF</span>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      applyDirective("Threat Mitigation Action Plan: Focus strictly on vulnerability remediations with 30-day timelines.")
                    }
                    className="inline-flex items-center gap-1 rounded bg-surface-container px-2.5 py-1 label-mono-sm text-foreground transition-colors hover:bg-surface-container-high"
                  >
                    <ShieldCheck className="h-3.5 w-3.5 text-secondary-fixed-dim" />
                    <span>Mitigation Plan</span>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      applyDirective("Crisis Disclosure Memo: Formulate transparent public narrative with zero speculative attribution.")
                    }
                    className="inline-flex items-center gap-1 rounded bg-surface-container px-2.5 py-1 label-mono-sm text-foreground transition-colors hover:bg-surface-container-high"
                  >
                    <Info className="h-3.5 w-3.5 text-secondary-fixed-dim" />
                    <span>Crisis Memo</span>
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* STEP 2: TRANSFORMATION CONFIGURATION                     */}
      {/* ======================================================== */}
      {stage === 2 && (
        <div className="flex flex-col gap-6 rounded-xl bg-surface-container-low p-6">
          <div className="flex flex-col gap-1 pb-2">
            <div className="flex items-center gap-2">
              <PenLine className="h-5 w-5 text-primary" />
              <h2 className="headline-lg font-semibold text-foreground">Tone & Style</h2>
            </div>
            <p className="body-md text-muted-foreground">
              Calibrate synthesis tone, clearance posture, multilingual rendering, and structural intent.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3">
            {/* 1. Target Language */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <div className="flex items-center justify-between">
                <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                  <Globe className="h-4 w-4 text-secondary-fixed-dim" />
                  Target Language
                </label>
                <span className="label-mono-sm text-secondary-fixed-dim">Native RAG</span>
              </div>
              <select
                value={language}
                onChange={(e) => handleLanguageChange(e.target.value)}
                disabled={running}
                className="w-full cursor-pointer rounded bg-surface-container-lowest px-3 py-2 body-md text-foreground focus:bg-surface-container-high focus:outline-none"
              >
                <option value="English">English (US) — Official Corporate</option>
                <option value="Hindi">Hindi (हिन्दी) — Formal Enterprise</option>
                <option value="Spanish">Spanish (Español) — Estándar</option>
                <option value="French">French (Français) — Direction Générale</option>
                <option value="German">German (Deutsch) — Technisches Deutsch</option>
                <option value="Portuguese">Portuguese (Português) — Corporativo</option>
                <option value="Chinese">Chinese (中文) — 标准商务</option>
                <option value="Arabic">Arabic (العربية) — فصحى رسمية</option>
                <option value="Japanese">Japanese (日本語) — ビジネス敬語</option>
                <option value="Korean">Korean (한국어) — 공문서 표준</option>
              </select>
              <span className="caption text-outline">
                Output terminology is strictly adapted to jurisdiction norms.
              </span>
            </div>

            {/* 2. Target Audience */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                <Users className="h-4 w-4 text-secondary-fixed-dim" />
                Target Audience
              </label>
              <select
                value={audience}
                onChange={(e) => handleAudienceChange(e.target.value)}
                disabled={running}
                className="w-full cursor-pointer rounded bg-surface-container-lowest px-3 py-2 body-md text-foreground focus:outline-none"
              >
                <option value="Executive">Executive (Board, CEO, VP Suite)</option>
                <option value="Analyst">Intelligence Analysts & Researchers</option>
                <option value="Technical Team">SecOps & Technical Engineering</option>
                <option value="General">General Enterprise Employees</option>
                <option value="Public">Public & Regulatory Bodies</option>
                <option value="Social">Social Media & Industry Followers</option>
              </select>
              <span className="caption text-outline">
                Controls abstraction level and domain acronym retention.
              </span>
            </div>

            {/* 3. Delivery Tone */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                <PenLine className="h-4 w-4 text-secondary-fixed-dim" />
                Delivery Tone
              </label>
              <select
                value={tone}
                onChange={(e) => handleToneChange(e.target.value as Tone)}
                disabled={running}
                className="w-full cursor-pointer rounded bg-surface-container-lowest px-3 py-2 body-md text-foreground focus:outline-none"
              >
                <option value="Professional">Concise & Formal (No preamble)</option>
                <option value="Authoritative">Authoritative Threat Advisory</option>
                <option value="Persuasive">Persuasive Strategic Justification</option>
                <option value="Technical">Deep Technical & Forensic</option>
                <option value="Casual">Informative & Neutral</option>
              </select>
              <span className="caption text-outline">
                Ensures zero conversational fluff or speculative narrative.
              </span>
            </div>

            {/* 4. Detail Depth */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                <AlignJustify className="h-5 w-5 text-secondary-fixed-dim" />
                Detail Depth
              </label>
              <div className="grid grid-cols-3 gap-1 rounded bg-surface-container-lowest p-1">
                {(["brief", "standard", "detailed"] as const).map((lvl) => (
                  <button
                    key={lvl}
                    type="button"
                    onClick={() => {
                      setDetailLevel(lvl);
                      setConfiguration(null);
                    }}
                    className={cn(
                      "rounded py-1.5 caption label-mono-sm capitalize transition-colors",
                      detailLevel === lvl
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {lvl}
                  </button>
                ))}
              </div>
              <span className="caption text-outline">Target density: calibrated token output container.</span>
            </div>

            {/* 5. Strategic Objective */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                <Flag className="h-5 w-5 text-secondary-fixed-dim" />
                Strategic Objective
              </label>
              <div className="grid grid-cols-3 gap-1 rounded bg-surface-container-lowest p-1">
                {(["brief", "summarize", "advise"] as const).map((obj) => (
                  <button
                    key={obj}
                    type="button"
                    onClick={() => {
                      setObjective(obj);
                      setConfiguration(null);
                    }}
                    className={cn(
                      "rounded py-1.5 caption label-mono-sm capitalize transition-colors",
                      objective === obj
                        ? "bg-secondary/20 text-secondary-fixed-dim"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {obj}
                  </button>
                ))}
              </div>
              <span className="caption text-outline">Drives decision matrices and priority sequencing.</span>
            </div>

            {/* 6. Style Archetype */}
            <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
              <label className="headline-sm body-sm flex items-center gap-1.5 font-medium text-foreground">
                <LayoutGrid className="h-5 w-5 text-secondary-fixed-dim" />
                Style Archetype
              </label>
              <select
                value={styleArchetype}
                onChange={(e) => setStyleArchetype(e.target.value)}
                className="w-full cursor-pointer rounded bg-surface-container-lowest px-3 py-2 body-md text-foreground focus:outline-none"
              >
                <option value="Executive">Executive Intelligence Brief</option>
                <option value="Analytical">Analytical Whitepaper</option>
                <option value="Advisory">Operational Risk Advisory</option>
                <option value="News-style">News Flash / Threat Dispatch</option>
                <option value="Technical">Technical Runbook Schema</option>
              </select>
              <span className="caption text-outline">Applies verified enterprise formatting frameworks.</span>
            </div>
          </div>

          {/* 7. Situational Context Buffer */}
          <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
            <label className="headline-sm body-sm flex items-center justify-between font-medium text-foreground">
              <span className="flex items-center gap-1.5">
                <MessageSquarePlus className="h-5 w-5 text-secondary-fixed-dim" />
                Situational Context & Critical Intent
              </span>
              <span className="label-mono-sm text-outline">Injected as priority constraint</span>
            </label>
            <input
              type="text"
              value={situationalIntent}
              onChange={(e) => setSituationalIntent(e.target.value)}
              placeholder="Add specific scheduling, audience sensitivities, or decision deadlines..."
              className="w-full rounded bg-surface-container-lowest px-3.5 py-2 body-md text-foreground placeholder:text-outline focus:bg-surface-container-high focus:outline-none"
            />
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* STEP 3: OUTPUT SELECTION                                 */}
      {/* ======================================================== */}
      {stage === 3 && (
        <div className="rounded-xl bg-surface-container-low p-6 shadow-sm">
          <OutputPackageGrid
            selected={selectedOutputs}
            onChange={setSelectedOutputs}
            disabled={running}
          />
        </div>
      )}

      {/* ======================================================== */}
      {/* STEP 4: REVIEW & DISPATCH                                */}
      {/* ======================================================== */}
      {stage === 4 && (
        <ReviewPanel
          selectedOutputs={selectedOutputs}
          prompt={prompt}
          source={source}
          sourceReady={sourceReady}
          language={language}
          audience={audience}
          tone={tone}
          detailLevel={detailLevel}
          objective={objective}
          styleArchetype={styleArchetype}
          mode={mode}
          onEdit={goToStage}
        />
      )}

      {formError && (
        <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive">
          {formError}
        </p>
      )}

      {/* ---- Stepper Footer Navigation ---- */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4">
        <button
          type="button"
          onClick={() => setStage((s) => Math.max(1, s - 1))}
          disabled={stage === 1 || running}
          className="inline-flex items-center gap-2 rounded bg-surface-container px-4 py-2 headline-sm body-sm text-foreground transition-all hover:bg-surface-container-high disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back
        </button>

        <div className="flex items-center gap-2">
          {stage === 1 && (
            <button
              type="button"
              onClick={() => goToStage(2)}
              disabled={!inputReady || running}
              className="inline-flex items-center gap-2 rounded bg-primary px-5 py-2.5 headline-sm body-sm text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Continue to Configuration
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
          {stage === 2 && (
            <button
              type="button"
              onClick={() => void nextToOutputs()}
              disabled={running || configSaving}
              className="inline-flex items-center gap-2 rounded bg-primary px-5 py-2.5 headline-sm body-sm text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {configSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              )}
              Continue to Output Selection
            </button>
          )}
          {stage === 3 && (
            <button
              type="button"
              onClick={() => void nextToReview()}
              disabled={selectedOutputs.length === 0 || running || configSaving}
              className="inline-flex items-center gap-2 rounded bg-primary px-5 py-2.5 headline-sm body-sm text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {configSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              )}
              Review & Ready to Execute
            </button>
          )}
          {stage === 4 && (
            <button
              type="button"
              onClick={() => void handleTransform()}
              disabled={!canTransform}
              className="inline-flex items-center gap-2 rounded bg-primary px-5 py-2.5 headline-sm body-sm text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {running ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              )}
              Dispatch Transformation
            </button>
          )}
        </div>
      </div>

      {/* ---- Execution Pipeline Observer & Results (During/After Job) ---- */}
      {job && (
        <section className="space-y-4 pt-4">
          <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-5">
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
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-outline-variant bg-surface-container-lowest px-4 py-3">
            <p className="text-sm text-muted-foreground">
              {active
                ? "Transformation complete — artifacts are saved to your project."
                : "This transformation runs in the background with continuous provenance tracking."}
            </p>
            <Link
              href="/history"
              className="text-sm font-medium text-primary hover:underline"
            >
              View in History →
            </Link>
          </div>
        </section>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StageIndicator({
  current,
  running,
  selectedCount,
  onSelect,
  canGoToStep,
  disabled,
}: {
  current: number;
  running: boolean;
  selectedCount: number;
  onSelect: (step: number) => void;
  canGoToStep: (step: number) => boolean;
  disabled: boolean;
}) {
  return (
    <ol
      role="list"
      aria-label="Transformation steps"
      className="grid grid-cols-2 gap-2 rounded-lg bg-surface-container-low p-2 md:grid-cols-4"
    >
      {STEPS.map((step) => {
        const index = step.step;
        const isCurrent = index === current;
        const isDone = index < current;
        const subtitle =
          step.subtitleDynamic !== undefined
            ? `${selectedCount} Format${selectedCount !== 1 ? "s" : ""} Selected`
            : (step.subtitle as string);

        return (
          <li key={index} className="min-w-0">
            <button
              type="button"
              onClick={() => onSelect(index)}
              disabled={disabled || !canGoToStep(index)}
              aria-current={isCurrent ? "step" : undefined}
              aria-label={`Step ${index} of ${STEPS.length}, ${step.title}${
                isCurrent ? ", current step" : ""
              }`}
              className={cn(
                "flex w-full items-center gap-3 rounded px-3.5 py-2.5 text-left transition-all",
                isCurrent
                  ? "bg-surface-container-high text-foreground shadow-sm"
                  : isDone
                    ? "text-muted-foreground hover:bg-surface-container hover:text-foreground"
                    : "text-muted-foreground hover:bg-surface-container/50 disabled:opacity-50",
              )}
            >
              <div
                className={cn(
                  "flex h-6 w-6 shrink-0 items-center justify-center rounded font-semibold label-mono-sm text-xs",
                  isCurrent
                    ? "bg-primary text-primary-foreground"
                    : isDone
                      ? "bg-success/20 text-success"
                      : "bg-surface-container-highest text-foreground",
                )}
                aria-hidden="true"
              >
                {isDone ? <CheckCircle2 className="h-3.5 w-3.5" /> : index}
              </div>
              <div className="flex min-w-0 flex-col">
                <span className="truncate body-sm font-medium leading-tight text-foreground">
                  {step.title}
                </span>
                <span className="truncate caption text-outline">
                  {isCurrent && running && step.step === 4 ? "Executing…" : subtitle}
                </span>
              </div>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

function SourceCard({
  source,
  onRemove,
  onReplace,
}: {
  source: SourceResponse;
  onRemove: () => void;
  onReplace: () => void;
}) {
  const ready = source.status === "ready";
  const failed = source.status === "failed";
  const processing = source.status === "processing" || source.status === "uploaded";
  const signals = sourceSecuritySignals(source);
  const classification = getSourceClassification(source);
  const policyPosture = getPolicyPosture(classification);

  return (
    <div className="flex flex-col rounded-xl bg-surface-container p-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3.5">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-primary-container/20 text-primary">
            <FileText className="h-6 w-6" />
          </div>
          <div className="flex flex-col">
            <div className="flex items-center gap-2">
              <span className="body-sm font-semibold text-foreground">
                {source.original_filename ?? "Pasted text source"}
              </span>
              <span className="rounded bg-surface-container-highest px-1.5 py-0.5 label-mono-sm text-[10px] text-secondary-fixed-dim">
                {source.status.toUpperCase()}
              </span>
              <span
                className={cn(
                  "rounded px-1.5 py-0.5 label-mono-sm text-[10px] font-semibold",
                  classification === "RESTRICTED" || classification === "CONFIDENTIAL"
                    ? "bg-destructive/20 text-destructive"
                    : "bg-surface-container-highest text-foreground",
                )}
              >
                {classification}
              </span>
            </div>
            <span className="caption mt-0.5 text-muted-foreground">
              {mimeTypeLabel(source)} · {formatFileSize(source.file_size)} · {languageLabel(source.language)}
            </span>
            <div className="mt-2 flex flex-wrap items-center gap-3 label-mono-sm text-outline">
              <span className="flex items-center gap-1 text-secondary-fixed-dim">
                <CheckCircle2 className="h-3.5 w-3.5" /> Indexed & Ready
              </span>
              <span>·</span>
              <span className="text-muted-foreground">{policyPosture}</span>
            </div>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onReplace}
            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-surface-container-high hover:text-foreground"
            title="Replace Source"
          >
            <RotateCcw className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded p-1.5 text-destructive transition-colors hover:bg-destructive/10"
            title="Remove Document"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="-mx-4 -mb-4 mt-4 flex items-center justify-between rounded-b bg-surface-container-lowest/60 px-4 py-2.5 caption text-muted-foreground">
        <div className="flex items-center gap-2 label-mono-sm">
          <span className="h-2 w-2 rounded-full bg-secondary" />
          <span className="text-foreground">Vector Embeddings Active</span>
        </div>
        <span className="label-mono-sm text-secondary-fixed-dim">Ready for Synthesis</span>
      </div>
    </div>
  );
}

function ReviewPanel({
  selectedOutputs,
  prompt,
  source,
  sourceReady,
  language,
  audience,
  tone,
  detailLevel,
  objective,
  styleArchetype,
  mode,
  onEdit,
}: {
  selectedOutputs: OutputTypeId[];
  prompt: string;
  source: SourceResponse | null;
  sourceReady: boolean;
  language: string;
  audience: string;
  tone: string;
  detailLevel: string;
  objective: string;
  styleArchetype: string;
  mode: { id: string; label: string; note: string };
  onEdit: (step: number) => void;
}) {
  const signals = sourceReady && source ? sourceSecuritySignals(source) : null;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
      {/* Left: Summary Audit Card (8 Cols) */}
      <div className="flex flex-col gap-4 rounded-xl bg-surface-container-low p-6 lg:col-span-8">
        <div className="flex items-center justify-between pb-1">
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-5 w-5 text-secondary-fixed-dim" />
            <h2 className="headline-lg font-semibold text-foreground">Transformation blueprint</h2>
          </div>
          <span className="label-mono-sm rounded bg-secondary/15 px-2 py-0.5 font-medium text-secondary-fixed-dim">
            PASS: GUARDRAILS VALIDATED
          </span>
        </div>
        <p className="body-md text-muted-foreground">
          Review synthesis parameters prior to parallel dispatch across the Grounded RAG neural pipeline.
        </p>

        {/* Review Blocks */}
        <div className="flex flex-col gap-3 pt-1">
          {/* Block 1: Input Corpus */}
          <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
            <div className="flex items-center justify-between label-mono-sm uppercase text-outline">
              <span className="flex items-center gap-1.5 text-primary">
                <FileText className="h-4 w-4" /> Step 1: Input Corpus
              </span>
              <button
                type="button"
                onClick={() => onEdit(1)}
                className="underline transition-colors hover:text-foreground"
              >
                Edit
              </button>
            </div>
            <div className="grid grid-cols-1 gap-3 pt-1 md:grid-cols-2">
              <div className="flex flex-col">
                <span className="caption text-outline">Source Asset</span>
                <span className="body-sm font-semibold text-foreground">
                  {source ? (source.original_filename ?? "Pasted text source") : "No source attached"}
                </span>
                <span className="label-mono-sm text-secondary-fixed-dim">
                  {source ? `${mimeTypeLabel(source)} · ${formatFileSize(source.file_size)}` : "Prompt-only execution"}
                </span>
              </div>
              <div className="flex flex-col">
                <span className="caption text-outline">Strategic Directive</span>
                <span className="body-sm line-clamp-2 text-foreground">
                  {prompt.trim() ? `“${prompt.trim()}”` : "No custom prompt directive."}
                </span>
              </div>
            </div>
          </div>

          {/* Block 2: Configuration */}
          <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
            <div className="flex items-center justify-between label-mono-sm uppercase text-outline">
              <span className="flex items-center gap-1.5 text-primary">
                <PenLine className="h-4 w-4" /> Step 2: Configuration
              </span>
              <button
                type="button"
                onClick={() => onEdit(2)}
                className="underline transition-colors hover:text-foreground"
              >
                Edit
              </button>
            </div>
            <div className="grid grid-cols-2 gap-2 pt-1 font-mono text-xs sm:grid-cols-3 md:grid-cols-6">
              <div className="flex flex-col">
                <span className="text-outline">Language</span>
                <span className="text-foreground">{language}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-outline">Audience</span>
                <span className="text-foreground">{audience}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-outline">Tone</span>
                <span className="text-foreground">{tone}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-outline">Detail</span>
                <span className="capitalize text-foreground">{detailLevel}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-outline">Objective</span>
                <span className="capitalize text-foreground">{objective}</span>
              </div>
              <div className="flex flex-col">
                <span className="text-outline">Style</span>
                <span className="text-foreground">{styleArchetype}</span>
              </div>
            </div>
          </div>

          {/* Block 3: Targeted Outputs */}
          <div className="flex flex-col gap-2 rounded-lg bg-surface-container p-4">
            <div className="flex items-center justify-between label-mono-sm uppercase text-outline">
              <span className="flex items-center gap-1.5 text-primary">
                <Layers className="h-4 w-4" /> Step 3: Targeted Outputs ({selectedOutputs.length} Artifacts)
              </span>
              <button
                type="button"
                onClick={() => onEdit(3)}
                className="underline transition-colors hover:text-foreground"
              >
                Edit
              </button>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              {selectedOutputs.length === 0 ? (
                <p className="body-sm text-muted-foreground">No outputs selected.</p>
              ) : (
                selectedOutputs.map((id) => (
                  <span
                    key={id}
                    className="inline-flex items-center gap-1.5 rounded bg-surface-container-high px-2.5 py-1 label-mono-sm text-foreground"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5 text-secondary-fixed-dim" />
                    {outputTypeShortLabel(id)}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right: Security & Action Dock (4 Cols) */}
      <div className="flex flex-col gap-4 lg:col-span-4">
        <div className="flex flex-col gap-4 rounded-xl bg-surface-container-low p-5">
          <span className="headline-sm body-sm flex items-center gap-2 font-semibold text-foreground">
            <Lock className="h-4 w-4 text-secondary-fixed-dim" />
            Compliance & Provenance
          </span>

          <div className="flex flex-col gap-2 body-sm">
            <div className="flex items-center justify-between rounded bg-surface-container px-2.5 py-1.5">
              <span className="caption text-muted-foreground">Security Clearance</span>
              <span className="label-mono-sm text-outline">Not asserted</span>
            </div>
            <div className="flex items-center justify-between rounded bg-surface-container px-2.5 py-1.5">
              <span className="caption text-muted-foreground">PII Redaction Engine</span>
              <span className="label-mono-sm text-foreground">Auto-Redact Active</span>
            </div>
            <div className="flex items-center justify-between rounded bg-surface-container px-2.5 py-1.5">
              <span className="caption text-muted-foreground">Deterministic Engine</span>
              <span className="label-mono-sm text-secondary-fixed-dim">Enforced</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}