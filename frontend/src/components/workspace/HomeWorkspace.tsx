/**
 * TransformIQ — Home transformation workspace.
 *
 * The primary enterprise workspace shown on Home (`/`).
 * Structurally aligned with the authoritative Stitch enterprise reference:
 *   1. Real System / Status Ticker
 *   2. Stitch-style Hero Section ("Transform information into communication")
 *   3. 3 Transformation Input Vectors (Source, Prompt, Source + Prompt)
 *   4. Primary Unified Composer (Prompt + Source + Tone + Audience + Multi-output)
 *   5. "What can you create?" — 7 Output Format Cards
 *   6. Controlled Transformation Pipeline Section (6 Stages)
 *   7. Recent Transformations (real existing API data, search/filters, Stitch empty state)
 *   8. Workspaces & Project Libraries (real project data)
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  Layers,
  Terminal,
  UploadCloud,
  ArrowRight,
  ShieldCheck,
  FolderOpen,
  History,
  Lock,
  Search,
  Workflow,
  BookOpen,
  ClipboardList,
  Share2,
  ShieldAlert,
  Presentation,
  Tag,
  BarChart3,
  Video,
  BadgeCheck,
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
  const router = useRouter();

  // ---- Environment (quick project) --------------------------------------
  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [quickProjectId, setQuickProjectId] = useState<string | null>(null);

  // ---- Composer inputs ---------------------------------------------------
  const [prompt, setPrompt] = useState("");
  const [source, setSource] = useState<SourceResponse | null>(null);
  const [sourceUploading, setSourceUploading] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerRef = useRef<HTMLDivElement>(null);

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
  const [sourceCount, setSourceCount] = useState(0);
  const [transformationCount, setTransformationCount] = useState(0);
  const [recentFilter, setRecentFilter] = useState<"all" | "completed" | "processing">("all");
  const [recentSearch, setRecentSearch] = useState("");

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
      setTransformationCount(quickHistoryRes.data.length);
      setRecentTransformations(quickHistoryRes.data.slice(0, 5));
    } catch {
      // non-fatal — recent lists stay empty
    }
  }, []);

  const boot = useCallback(async () => {
    setPhase("loading");
    try {
      const quick = await ensureQuickProject();
      setProject(quick);
      setQuickProjectId(quick.id);

      const [sourcesRes, configsRes] = await Promise.all([
        sourcesApi.list(quick.id),
        configurationsApi.list(quick.id),
      ]);
      if (sourcesRes.data.length > 0) setSource(sourcesRes.data[0]);
      setSourceCount(sourcesRes.data.length);
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
      const s = await waitForReady(res.data.id);
      setSource(s);
      setSourceCount((c) => c + 1);
      setConfiguration(null);
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

    const selectedProvider =
      typeof window !== "undefined"
        ? localStorage.getItem("transformiq.llm_provider")
        : null;

    const payload = {
      project_id: quickProjectId,
      configuration_id: cfg.id,
      output_types: selectedOutputs,
      ...(prompt.trim() ? { prompt: prompt.trim() } : {}),
      ...(source ? { source_id: source.id } : {}),
      ...(selectedProvider && selectedProvider !== "server"
        ? { llm_provider: selectedProvider }
        : {}),
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
      // non-fatal
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
    onError: (err) => {
      setPollErrorMsg(
        errorMessage(err, "Trouble checking job status; will keep trying…"),
      );
    },
    onDone: (j) => {
      setJob(j);
      void refreshOutputs(j.id);
      if (j.status === "completed") {
        setPhase("completed");
        if (quickProjectId) void loadRecent(quickProjectId);
      } else if (j.status === "failed") {
        setPhase("failed");
        setFormError(j.error_message ?? "Transformation encountered an error.");
        if (quickProjectId) void loadRecent(quickProjectId);
      }
    },
  });

  useEffect(() => {
    if (polledJob) {
      setJob(polledJob);
      if (!isTerminalJobStatus(polledJob.status)) {
        setPhase("processing");
      }
    }
  }, [polledJob]);

  const running = phase === "generating" || phase === "processing";

  const phaseLabel =
    phase === "loading"
      ? "Loading…"
      : phase === "generating" || phase === "processing"
        ? "Running"
        : phase === "completed"
          ? "Completed"
          : phase === "failed"
            ? "Failed"
            : "Idle";

  // Filtered recent transformations
  const filteredRecent = useMemo(() => {
    return recentTransformations.filter((j) => {
      if (recentFilter === "completed" && j.status !== "completed") return false;
      if (recentFilter === "processing" && (j.status === "completed" || j.status === "failed"))
        return false;
      if (recentSearch.trim()) {
        const q = recentSearch.toLowerCase();
        const types = (j.requested_outputs as { output_types?: string[] })?.output_types ?? [];
        const matchType = types.some((t) => t.toLowerCase().includes(q));
        const matchId = j.id.toLowerCase().includes(q);
        if (!matchType && !matchId) return false;
      }
      return true;
    });
  }, [recentTransformations, recentFilter, recentSearch]);

  const scrollToComposer = (focusTarget?: "source" | "prompt") => {
    composerRef.current?.scrollIntoView({ behavior: "smooth" });
    if (focusTarget === "source" && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleSelectOutputCard = (id: OutputTypeId) => {
    if (!selectedOutputs.includes(id)) {
      setSelectedOutputs([...selectedOutputs, id]);
    }
    scrollToComposer();
  };

  return (
    <div className="flex flex-col space-y-10">
      {/* 1. Top System / Status Ticker */}
      <div className="flex w-full flex-wrap items-center justify-between gap-4 rounded-xl bg-surface-container-lowest p-3.5 shadow-sm">
        <div className="flex flex-wrap items-center gap-6">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-secondary animate-pulse" aria-hidden="true" />
            <span className="label-mono-sm uppercase tracking-wider text-muted-foreground">
              Engine: Orchestrated
            </span>
          </div>
          <div className="hidden h-3 w-px bg-surface-container-highest sm:block" aria-hidden="true" />
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-secondary-fixed-dim" aria-hidden="true" />
            <span className="body-sm text-foreground">
              Grounding: <span className="label-mono-sm font-semibold text-secondary-fixed-dim">Multi-Document RAG Enforced</span>
            </span>
          </div>
          <div className="hidden h-3 w-px bg-surface-container-highest md:block" aria-hidden="true" />
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="label-mono-xs uppercase text-muted-foreground">
              Sources · {sourceCount}
            </span>
          </div>
          <div className="hidden h-3 w-px bg-surface-container-highest md:block" aria-hidden="true" />
          <div className="flex items-center gap-2">
            <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
            <span className="label-mono-xs uppercase text-muted-foreground">
              Transformations · {transformationCount}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-3">

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
      </div>

      {/* 2. Hero Section */}
      <section className="relative overflow-hidden rounded-2xl bg-gradient-to-b from-surface-container to-surface-container-low p-8 shadow-md lg:p-10">
        <div
          className="pointer-events-none absolute -mt-20 -mr-20 right-0 top-0 h-96 w-96 rounded-full bg-primary-container/10 blur-3xl"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -mb-16 left-1/3 bottom-0 h-80 w-80 rounded-full bg-secondary/5 blur-2xl"
          aria-hidden="true"
        />
        <div className="relative z-10 max-w-4xl space-y-6">
          <div className="inline-flex items-center gap-2 rounded bg-surface-container-highest px-3 py-1 text-secondary-fixed-dim shadow-sm">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            <span className="label-mono-sm uppercase tracking-wider">
              Automated Enterprise Transformation Engine
            </span>
          </div>
          <div className="space-y-3">
            <h1 className="headline-xl font-semibold tracking-tight text-foreground">
              Transform information into{" "}
              <span className="bg-gradient-to-r from-primary to-tertiary bg-clip-text text-transparent">
                communication
              </span>
              .
            </h1>
            <p className="body-lg max-w-2xl leading-relaxed text-muted-foreground">
              Transform documents and prompts into grounded, ready-to-use content.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-4 pt-2">
            <Link
              href="/create"
              id="open-new-trans-modal"
              className="inline-flex items-center gap-2.5 rounded-lg bg-primary px-5 py-3 headline-sm text-primary-foreground shadow-[0_0_16px_rgba(37,99,235,0.4)] transition-all hover:bg-primary/90 active:scale-[0.98]"
            >
              <Plus className="h-4 w-4 stroke-[3]" />
              <span>+ Create Transformation</span>
            </Link>
            <Link
              href="/history"
              className="inline-flex items-center gap-2 rounded-lg bg-surface-container-high px-4 py-3 body-md text-foreground shadow-sm transition-colors hover:bg-surface-container-highest"
            >
              <History className="h-4 w-4 text-muted-foreground" />
              <span>View Transformation History</span>
            </Link>
            <div className="flex items-center gap-2 rounded-lg bg-surface-container-lowest px-3.5 py-2.5 text-muted-foreground shadow-inner">
              <span className="h-2 w-2 rounded-full bg-secondary-fixed-dim" />
              <span className="label-mono-sm">Source Grounding: Multi-Document RAG Enabled</span>
            </div>
          </div>
        </div>
      </section>

      {/* 3. 3 Transformation Input Vectors ("Create a new transformation") */}
      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-1 sm:flex-row sm:items-baseline">
          <div>
            <h2 className="headline-lg font-semibold tracking-tight text-foreground">
              Create a new transformation
            </h2>
            <p className="body-md text-muted-foreground">
              Start with a source, a prompt, or both.
            </p>
          </div>
          <span className="label-mono-sm uppercase text-outline">
            CHOOSE AN INPUT MODE
          </span>
        </div>

        <div className="grid grid-cols-1 gap-5 md:grid-cols-3">
          {/* Card 1: Source */}
          <div
            onClick={() => router.push("/create")}
            className="group relative flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-6 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-surface-container-highest text-secondary-fixed-dim transition-transform group-hover:scale-105">
                  <UploadCloud className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 uppercase text-muted-foreground">
                  SOURCE
                </span>
              </div>
              <div>
                <h3 className="headline-sm flex items-center gap-2 font-semibold text-foreground">
                  Source Corpus
                  <ArrowRight className="h-4 w-4 text-outline opacity-0 transition-opacity group-hover:opacity-100" />
                </h3>
                <p className="body-sm mt-2 leading-relaxed text-muted-foreground">
                  Upload documents and ground outputs in your source material.
                </p>
              </div>
            </div>
            <div className="space-y-3 pt-6">
              <div className="flex flex-wrap gap-2">
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-secondary-fixed-dim">
                  Multi-file supported
                </span>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  Auto-extraction
                </span>
              </div>
              <div className="flex items-center justify-between pt-2">
                <span className="caption text-outline">STIX, PDF, CSV, MD, DOCX</span>
                <ArrowRight className="h-4 w-4 text-secondary-fixed-dim transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </div>

          {/* Card 2: Prompt */}
          <div
            onClick={() => router.push("/create")}
            className="group relative flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-6 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-surface-container-highest text-primary transition-transform group-hover:scale-105">
                  <Terminal className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 uppercase text-muted-foreground">
                  PROMPT
                </span>
              </div>
              <div>
                <h3 className="headline-sm flex items-center gap-2 font-semibold text-foreground">
                  Prompt
                  <ArrowRight className="h-4 w-4 text-outline opacity-0 transition-opacity group-hover:opacity-100" />
                </h3>
                <p className="body-sm mt-2 leading-relaxed text-muted-foreground">
                  Guide the output with instructions, audience, tone, and format.
                </p>
              </div>
            </div>
            <div className="space-y-3 pt-6">
              <div className="flex flex-wrap gap-2">
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-primary">
                  Template presets
                </span>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  Tone control
                </span>
              </div>
              <div className="flex items-center justify-between pt-2">
                <span className="caption text-outline">Persona, Mandate, Severity rules</span>
                <ArrowRight className="h-4 w-4 text-primary transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </div>

          {/* Card 3: Source + Prompt (Highlighted) */}
          <div
            onClick={() => router.push("/create")}
            className="group relative flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container-high p-6 shadow-md ring-1 ring-primary/40 transition-all hover:bg-surface-container-highest"
          >
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-[0_0_12px_rgba(37,99,235,0.3)] transition-transform group-hover:scale-105">
                  <Layers className="h-6 w-6" />
                </div>
                <div className="flex items-center gap-1.5 rounded-full bg-secondary/15 px-2.5 py-0.5 text-secondary-fixed-dim">
                  <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
                  <span className="label-mono-sm uppercase font-semibold">Recommended</span>
                </div>
              </div>
              <div>
                <h3 className="headline-sm flex items-center gap-2 font-semibold text-foreground">
                  Source + Prompt
                  <ArrowRight className="h-4 w-4 text-secondary-fixed-dim opacity-0 transition-opacity group-hover:opacity-100" />
                </h3>
                <p className="body-sm mt-2 leading-relaxed text-muted-foreground">
                  Combine source material with instructions for grounded, targeted outputs.
                </p>
              </div>
            </div>
            <div className="space-y-3 pt-6">
              <div className="flex flex-wrap gap-2">
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 font-medium text-secondary-fixed-dim">
                  Grounded
                </span>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-tertiary">
                  Provenance tracked
                </span>
              </div>
              <div className="flex items-center justify-between pt-2">
                <span className="caption text-secondary-fixed-dim">Verification pipeline</span>
                <ArrowRight className="h-4 w-4 text-secondary-fixed-dim transition-transform group-hover:translate-x-1" />
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 4. Primary Unified Composer Section */}
      <div ref={composerRef} className="space-y-6 rounded-2xl border border-border-subtle bg-surface-container-low p-6 lg:p-8">
        <div className="space-y-1 pb-2">
          <div className="flex items-center gap-2">
            <Workflow className="h-5 w-5 text-primary" />
            <span className="label-mono-xs uppercase text-muted-foreground">Unified Composer</span>
          </div>
          <h2 className="headline-md font-semibold text-foreground">What would you like to transform?</h2>
          <p className="body-sm text-muted-foreground">
            Configure your transformation here or use the guided 4-step workflow at{" "}
            <Link href="/create" className="text-primary hover:underline">
              /create
            </Link>.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Mandate — full width */}
          <section className="space-y-2 lg:col-span-2">
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">
                Prompt
              </span>
              <h2 className="headline-md font-semibold text-foreground">Mandate</h2>
              <p className="text-xs text-muted-foreground">
                Describe what you want KaryaSetu AI to create. A source is optional
                — the instruction alone is enough to transform.
              </p>
            </div>

            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest shadow-sm">
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe what you want KaryaSetu AI to create…"
                rows={4}
                aria-label="Transformation prompt"
                className="w-full resize-y rounded-t-xl border-0 bg-transparent px-5 py-4 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
              />

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-outline-variant px-3 py-2.5">
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
                    className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors"
                  >
                    <Mic className="h-4 w-4" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>
          </section>

          {/* Source */}
          <section className="space-y-2">
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">
                Input vector 02 · Corpus
              </span>
              <h2 className="headline-md font-semibold text-foreground">Source</h2>
              <p className="text-xs text-muted-foreground">
                Attach the material to transform. KaryaSetu AI ingests and analyzes
                it before transforming.
              </p>
            </div>

            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 shadow-sm">
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
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">Style</span>
              <h2 className="headline-md font-semibold text-foreground">Tone</h2>
              <p className="text-xs text-muted-foreground">
                Use a consistent voice across every deliverable.
              </p>
            </div>
            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 shadow-sm">
              <ToneSelector value={tone} onChange={handleToneChange} disabled={running} />
            </div>
          </section>

          {/* Audience */}
          <section className="space-y-2">
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">Audience</span>
              <h2 className="headline-md font-semibold text-foreground">Audience</h2>
              <p className="text-xs text-muted-foreground">
                Who are the outputs written for?
              </p>
            </div>
            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 shadow-sm">
              <AudienceSelector
                value={audience}
                onChange={handleAudienceChange}
                disabled={running}
              />
            </div>
          </section>

          {/* Output language */}
          <section className="space-y-2">
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">Locale</span>
              <h2 className="headline-md font-semibold text-foreground">
                Output language
              </h2>
              <p className="text-xs text-muted-foreground">
                Write the outputs in this language.
              </p>
            </div>
            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 shadow-sm">
              <LanguageSelector
                value={language}
                onChange={handleLanguageChange}
                disabled={running}
              />
            </div>
          </section>

          {/* Deliverables — full width */}
          <section className="space-y-2 lg:col-span-2">
            <div className="space-y-0.5">
              <span className="label-mono-xs uppercase text-muted-foreground">
                Output packages
              </span>
              <h2 className="headline-md font-semibold text-foreground">Deliverables</h2>
              <p className="text-xs text-muted-foreground">
                Select one or more output formats. KaryaSetu AI will create them
                from the same source and instructions.
              </p>
            </div>
            <div className="rounded-xl border border-outline-variant bg-surface-container-lowest p-4 shadow-sm">
              <OutputSelector
                selected={selectedOutputs}
                onChange={setSelectedOutputs}
                disabled={running}
              />
            </div>
          </section>

          {/* Orchestration summary */}
          {selectedOutputs.length > 0 && (
            <section className="rounded-xl border border-primary/25 bg-primary-container/20 p-4 lg:col-span-2">
              <p className="text-sm font-medium text-foreground">
                {selectedOutputs.length} output{selectedOutputs.length !== 1 ? "s" : ""}{" "}
                selected
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                KaryaSetu AI will generate:
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
                . Outputs will be written in {language || "English"}.
              </p>
            </section>
          )}

          <p className="flex items-start gap-2 rounded-xl border border-outline-variant bg-surface-container-lowest px-3 py-2.5 text-xs text-muted-foreground lg:col-span-2">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
            Every deliverable is grounded in your source with inline citations, so
            you can trace each claim back to the originating content before using
            it.
          </p>

          {formError && (
            <p role="alert" className="rounded-md bg-destructive/10 px-3 py-2 text-xs font-medium text-destructive lg:col-span-2">
              {formError}
            </p>
          )}
        </div>

        {/* Run CTA */}
        <div className="flex flex-col items-center gap-2 pt-2">
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
          </section>
        )}
      </div>

      {/* 5. "What can you create?" — 7 Output Categories Grid */}
      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-2 md:flex-row md:items-end">
          <div>
            <div className="mb-1 flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-secondary-fixed-dim" />
              <span className="label-mono-sm uppercase tracking-wider text-secondary-fixed-dim">
                Multi-Format Dispatch
              </span>
            </div>
            <h2 className="headline-lg font-semibold tracking-tight text-foreground">
              What can you create?
            </h2>
            <p className="body-md max-w-2xl text-muted-foreground">
              Select one or bundle multiple communication formats generated simultaneously from a single validated source dossier.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setSelectedOutputs(["summary", "linkedin", "advisory", "presentation", "x", "infographic", "video"]);
                scrollToComposer();
              }}
              className="rounded bg-surface-container-high px-3 py-1.5 body-sm text-foreground transition-colors hover:bg-surface-container-highest"
            >
              Select All Formats
            </button>
            <button
              onClick={() => {
                setSelectedOutputs(["summary", "advisory"]);
                scrollToComposer();
              }}
              className="rounded bg-surface-container px-3 py-1.5 body-sm text-muted-foreground transition-colors hover:bg-surface-container-high hover:text-foreground"
            >
              Executive Presets
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {/* 1. Executive Summary (Spans 2 columns on larger displays) */}
          <div
            onClick={() => handleSelectOutputCard("summary")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high sm:col-span-2"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <ClipboardList className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  1-2 Pages · Strict Evidence
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">Executive Summary</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                High-level risk assessments, decision matrices, and bottom-line-up-front (BLUF) briefings calibrated for Board of Directors and C-suite consumption.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Output: PDF / Structured Markdown</span>
              <span className="label-mono-sm flex items-center gap-1 text-primary group-hover:underline">
                Add to Composer <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </div>
          </div>

          {/* 2. LinkedIn Post */}
          <div
            onClick={() => handleSelectOutputCard("linkedin")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-secondary-fixed-dim transition-colors group-hover:bg-secondary-container group-hover:text-on-secondary-container">
                  <Share2 className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  Executive Tone · MD
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">LinkedIn Post</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Public stakeholder updates, thought leadership briefs, and corporate cyber resilience announcements.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">TLP:CLEAR public format</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>

          {/* 3. Tactical Advisory */}
          <div
            onClick={() => handleSelectOutputCard("advisory")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-warning transition-colors group-hover:bg-warning/20">
                  <ShieldAlert className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  CVE / TLP Aware
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">Tactical Advisory</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Cybersecurity advisories, operational guidance, patch priority ladders, and remediation instructions.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Mitre ATT&CK Mapped</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>

          {/* 4. Presentation */}
          <div
            onClick={() => handleSelectOutputCard("presentation")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-tertiary transition-colors group-hover:bg-tertiary-container group-hover:text-on-tertiary-container">
                  <Presentation className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  8-12 Slide Deck
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">Presentation</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Board-ready visual outlines, narrative arcs, metric callouts, and quarterly transformation briefs.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Export: PPTX, Keynote</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>

          {/* 5. X Thread */}
          <div
            onClick={() => handleSelectOutputCard("x")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-secondary-fixed-dim transition-colors group-hover:bg-surface-bright">
                  <Tag className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  280 Char Rules
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">X Thread</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Rapid incident communications, sequential telemetry highlights, and public advisory broadcast series.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Numbered Post Chains</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>

          {/* 6. Infographic Blueprint */}
          <div
            onClick={() => handleSelectOutputCard("infographic")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                  <BarChart3 className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  Structured SVG/Data
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">Infographic Blueprint</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Architecture diagrams, timeline callouts, attack pathway schematics, and quantitative metric layouts.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Vector-ready Spec</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>

          {/* 7. Video Package (Script spec, no MP4 rendering) */}
          <div
            onClick={() => handleSelectOutputCard("video")}
            className="group flex cursor-pointer flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
          >
            <div>
              <div className="flex items-start justify-between">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-container-highest text-tertiary transition-colors group-hover:bg-tertiary-container group-hover:text-on-tertiary-container">
                  <Video className="h-6 w-6" />
                </div>
                <span className="label-mono-sm rounded bg-surface-container-lowest px-2 py-0.5 text-muted-foreground">
                  Voiceover & Cues
                </span>
              </div>
              <h3 className="headline-sm mt-4 font-semibold text-foreground">Video Package</h3>
              <p className="body-sm mt-1.5 leading-relaxed text-muted-foreground">
                Complete presenter teleprompter script, visual B-roll cues, graphic lower-third triggers, and narrative storyboard.
              </p>
            </div>
            <div className="mt-2 flex items-center justify-between pt-4">
              <span className="caption text-outline">Timed Script & Directives</span>
              <Plus className="h-4 w-4 text-outline transition-colors group-hover:text-foreground" />
            </div>
          </div>
        </div>
      </section>

      {/* 6. Controlled Transformation Pipeline (6-Stage Ribbon) */}
      <section className="space-y-6 rounded-2xl bg-surface-container p-6 shadow-md lg:p-7">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div>
            <div className="flex items-center gap-2">
              <BadgeCheck className="h-5 w-5 text-secondary-fixed-dim" />
              <h2 className="headline-md font-semibold text-foreground">
                Controlled Transformation Pipeline
              </h2>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
          </div>
        </div>

        <div className="grid grid-cols-1 gap-3 pt-2 sm:grid-cols-2 lg:grid-cols-6">
          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 01</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Input Ingestion</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                OCR, multi-modal parser, PDF text tree extraction & chunking.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">Normalizer</div>
          </div>

          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 02</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Security & DLP</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                Automated PII scrubbing, secret detection & boundary checks.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">DLP Filter</div>
          </div>

          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 03</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Context & RAG</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                Vector index, semantic proximity pairing & source anchoring.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">Dense Retrieval</div>
          </div>

          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 04</span>
              <span className="h-2 w-2 rounded-full bg-secondary animate-pulse" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Controlled Synthesis</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                Target schema adherence, persona injection & constrained execution.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">Temp: 0.15 Deterministic</div>
          </div>

          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 05</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Evidence Audit</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                Line-by-line citation verification against ingested source dossier chunks.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">Zero Speculation</div>
          </div>

          <div className="flex flex-col justify-between space-y-3 rounded-lg bg-surface-container-lowest p-3.5">
            <div className="flex items-center justify-between">
              <span className="label-mono-sm font-bold text-secondary-fixed-dim">STAGE 06</span>
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
            </div>
            <div>
              <div className="body-sm font-semibold text-foreground">Artifact Integrity</div>
              <p className="caption mt-1 leading-normal text-muted-foreground">
                Cryptographic hash stamping, audit log commit & rendering.
              </p>
            </div>
            <div className="label-mono-sm text-[10px] text-outline">SHA-256 Validated</div>
          </div>
        </div>
      </section>

      {/* 7. Recent Transformations Section */}
      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-4 lg:flex-row lg:items-center">
          <div>
            <h2 className="headline-lg font-semibold tracking-tight text-foreground">
              Recent Transformations
            </h2>
            <p className="body-md text-muted-foreground">
              Live audit ledger of multi-format generation runs and verified outputs.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center rounded-lg bg-surface-container p-1">
              <button
                onClick={() => setRecentFilter("all")}
                className={cn(
                  "rounded px-3 py-1 body-sm transition-colors",
                  recentFilter === "all"
                    ? "bg-surface-container-highest text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                All ({recentTransformations.length})
              </button>
              <button
                onClick={() => setRecentFilter("completed")}
                className={cn(
                  "rounded px-3 py-1 body-sm transition-colors",
                  recentFilter === "completed"
                    ? "bg-surface-container-highest text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Completed ({recentTransformations.filter((j) => j.status === "completed").length})
              </button>
              <button
                onClick={() => setRecentFilter("processing")}
                className={cn(
                  "rounded px-3 py-1 body-sm transition-colors",
                  recentFilter === "processing"
                    ? "bg-surface-container-highest text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                Running ({recentTransformations.filter((j) => j.status !== "completed" && j.status !== "failed").length})
              </button>
            </div>
            <div className="flex w-full items-center gap-2 rounded-lg bg-surface-container px-3 py-1.5 sm:w-64">
              <Search className="h-4 w-4 text-outline" />
              <input
                type="text"
                value={recentSearch}
                onChange={(e) => setRecentSearch(e.target.value)}
                placeholder="Filter jobs or formats..."
                className="w-full bg-transparent body-sm text-foreground placeholder:text-outline focus:outline-none"
              />
            </div>
          </div>
        </div>

        {/* List of Transformations or Clean Slate Empty State */}
        {recentTransformations.length === 0 ? (
          <div className="flex flex-col items-center justify-center space-y-5 rounded-xl bg-surface-container p-12 text-center shadow-sm">
            <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-surface-container-highest text-secondary-fixed-dim">
              <Layers className="h-8 w-8" />
            </div>
            <div className="max-w-md space-y-2">
              <h3 className="headline-md font-semibold text-foreground">No transformations yet</h3>
              <p className="body-md text-muted-foreground">
                Start with a source document, an analytical prompt, or both to generate your first verified communication artifacts.
              </p>
            </div>
            <Link
              href="/create"
              className="inline-flex items-center gap-2 rounded bg-primary px-5 py-2.5 headline-sm text-primary-foreground shadow-[0_0_12px_rgba(37,99,235,0.3)] transition-all hover:bg-primary/90"
            >
              <Plus className="h-4 w-4 stroke-[3]" />
              <span>+ Create Transformation</span>
            </Link>
          </div>
        ) : filteredRecent.length === 0 ? (
          <div className="rounded-xl border border-border-subtle bg-surface-container p-8 text-center text-sm text-muted-foreground">
            No transformations match your current filter.
          </div>
        ) : (
          <div className="space-y-3">
            {filteredRecent.map((j) => {
              const types = (j.requested_outputs as { output_types?: string[] })?.output_types ?? ["output"];
              const isDone = j.status === "completed";
              const isRunning = !isTerminalJobStatus(j.status);
              return (
                <Link
                  key={j.id}
                  href="/history"
                  className="flex flex-col justify-between gap-3 rounded-xl bg-surface-container p-4 shadow-sm transition-colors hover:bg-surface-container-high md:flex-row md:items-center sm:p-5"
                >
                  <div className="flex items-start gap-3.5">
                    <div className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-surface-container-highest text-secondary-fixed-dim">
                      <FileText className="h-5 w-5" />
                    </div>
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="headline-sm font-semibold text-foreground">
                          Transformation #{j.id.slice(0, 8)}
                        </span>
                        <span
                          className={cn(
                            "label-mono-sm rounded px-2 py-0.5 font-medium",
                            isDone
                              ? "bg-emerald-500/10 text-emerald-400"
                              : isRunning
                                ? "bg-amber-500/10 text-amber-400"
                                : "bg-red-500/10 text-red-400",
                          )}
                        >
                          {j.status.toUpperCase()}
                        </span>
                        <span className="inline-flex items-center gap-1 rounded bg-surface-container-lowest px-2 py-0.5 label-mono-sm text-secondary-fixed-dim">
                          <CheckCircle2 className="h-3.5 w-3.5" /> Grounded RAG
                        </span>
                      </div>
                      <div className="caption mt-1 flex flex-wrap items-center gap-3 text-muted-foreground">
                        <span>Updated {timeAgo(j.created_at)}</span>
                        <span>•</span>
                        <span>{types.length} Deliverables</span>
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 self-start md:self-center">
                    <span className="label-mono-sm text-outline hidden xl:inline">OUTPUTS:</span>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {types.map((t) => (
                        <span
                          key={t}
                          className="rounded bg-surface-container-lowest px-2 py-0.5 label-mono-sm text-primary"
                        >
                          {outputTypeShortLabel(t)}
                        </span>
                      ))}
                    </div>
                    <span className="ml-1 rounded p-2 text-muted-foreground transition-colors hover:bg-surface-container-highest hover:text-foreground">
                      <ArrowRight className="h-4 w-4" />
                    </span>
                  </div>
                </Link>
              );
            })}
          </div>
        )}
      </section>

      {/* 8. Workspaces & Project Libraries Section */}
      <section className="space-y-4">
        <div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
          <div>
            <h2 className="headline-lg font-semibold tracking-tight text-foreground">
              Workspaces & Project Libraries
            </h2>
            <p className="body-md text-muted-foreground">
              Compartmentalized security domains with independent RAG vector stores.
            </p>
          </div>
          <Link
            href="/projects"
            className="inline-flex items-center gap-1.5 self-start rounded bg-surface-container-high px-3.5 py-2 body-sm text-foreground shadow-sm transition-colors hover:bg-surface-container-highest sm:self-auto"
          >
            <FolderOpen className="h-4 w-4" />
            <span>+ View Projects</span>
          </Link>
        </div>

        {recentProjects.length === 0 ? (
          <div className="rounded-xl bg-surface-container p-6 text-center text-sm text-muted-foreground">
            No projects found.
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {recentProjects.map((p) => (
              <Link
                key={p.id}
                href={`/projects/${p.id}`}
                className="group flex flex-col justify-between rounded-xl bg-surface-container p-5 shadow-sm transition-all hover:bg-surface-container-high"
              >
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <FolderOpen className="h-5 w-5 text-secondary-fixed-dim" />
                    <span className="label-mono-sm text-outline">
                      {timeAgo(p.updated_at)}
                    </span>
                  </div>
                  <div>
                    <h3 className="headline-sm font-semibold text-foreground transition-colors group-hover:text-primary">
                      {isQuickProjectName(p.name) ? "Quick Transformations" : p.name}
                    </h3>
                    <p className="body-sm mt-1 line-clamp-2 leading-normal text-muted-foreground">
                      {p.description || "Active isolated enclave for grounded transformations."}
                    </p>
                  </div>
                </div>
                <div className="mt-4 flex items-center justify-between border-t border-outline-variant/30 pt-3">
                  <span className="body-sm text-primary group-hover:underline">Open Workspace</span>
                  <ArrowRight className="h-4 w-4 text-muted-foreground transition-transform group-hover:translate-x-1" />
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
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
