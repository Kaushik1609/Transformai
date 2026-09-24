"use client";

import React, { useState, useRef, useEffect, useMemo } from "react";
import { useTheme } from "@/components/theme";
import {
  FileText,
  Shield,
  Layers,
  Lock,
  Database,
  Cpu,
  Search,
  FileCheck2,
  Presentation,
  Image as ImageIcon,
  Share2,
  Film,
  Fingerprint,
  Play,
  Pause,
  RotateCcw,
  Maximize2,
  Minimize2,
  Info,
  CheckCircle2,
  ArrowRight,
  ExternalLink,
  Sliders,
  Zap,
  X,
} from "lucide-react";

export type FilterCategory = "all" | "security" | "rag" | "transformation" | "provenance";

export interface WorkflowNode {
  id: string;
  name: string;
  subtitle: string;
  badge: string;
  x: number;
  y: number;
  color: string;
  ringColor: string;
  haloColor: string;
  category: "ingest" | "security" | "vector" | "routing" | "intelligence" | "output" | "provenance";
  icon: React.ComponentType<{ className?: string }>;
  description: string;
  guarantee: string;
  inputFormat: string;
  outputFormat: string;
}

export interface WorkflowEdge {
  id: string;
  from: string;
  to: string;
  path: string;
  badge: string;
  lineStyle: "solid" | "dashed" | "dotted";
  color: string;
  particleColor: string;
  category: "security" | "rag" | "transformation" | "provenance";
  speed: number; // duration in seconds
  pillOffset?: { dx?: number; dy?: number };
}

const NODES: WorkflowNode[] = [
  {
    id: "source",
    name: "Authoritative Source Ingestion",
    subtitle: "Gazette · Policy · PDF / DOCX",
    badge: "SRC",
    x: 100,
    y: 360,
    color: "#2563eb",
    ringColor: "#3b82f6",
    haloColor: "rgba(59, 130, 246, 0.22)",
    category: "ingest",
    icon: FileText,
    description: "Accepts high-stakes institutional source documents. Computes an immutable SHA-256 digest at the instant of upload before any processing begins.",
    guarantee: "Anchored with SHA-256 hash. Zero data mutation.",
    inputFormat: "PDF, DOCX, TXT, Gazette Notifications",
    outputFormat: "Stored Original + Metadata Hash Anchor",
  },
  {
    id: "security",
    name: "Perimeter Security & Screening",
    subtitle: "Deterministic PII · ClamAV",
    badge: "SEC",
    x: 320,
    y: 190,
    color: "#d97706",
    ringColor: "#f59e0b",
    haloColor: "rgba(245, 158, 11, 0.22)",
    category: "security",
    icon: Shield,
    description: "Runs deterministic Luhn/regex PII detection, ClamAV anti-malware verification, and prompt injection defense barriers to fail-closed on malicious payloads.",
    guarantee: "Fails closed if malware detected. PII masked without model leaks.",
    inputFormat: "Extracted Text Streams",
    outputFormat: "Screened Content + Security Audit Events",
  },
  {
    id: "chunker",
    name: "Deterministic Chunker",
    subtitle: "Bounded Size · Offset Map",
    badge: "CHK",
    x: 320,
    y: 530,
    color: "#2563eb",
    ringColor: "#60a5fa",
    haloColor: "rgba(96, 165, 250, 0.22)",
    category: "vector",
    icon: Layers,
    description: "Splits authoritative text into bounded token chunks with exact character start/end coordinates. Every chunk receives a unique UUID for verifiable citation.",
    guarantee: "Strict boundary mapping. Zero overlap hallucination.",
    inputFormat: "Normalized Source Text",
    outputFormat: "Array of SourceChunk Records with Exact Offsets",
  },
  {
    id: "policy",
    name: "Zero-Trust Policy Engine",
    subtitle: "PUBLIC · RESTRICTED Rules",
    badge: "POL",
    x: 530,
    y: 140,
    color: "#059669",
    ringColor: "#10b981",
    haloColor: "rgba(16, 185, 129, 0.22)",
    category: "security",
    icon: Lock,
    description: "Ironclad policy gate: 'LLM may recommend, policy engine must decide.' Evaluates document classification, destination channels, and user permissions.",
    guarantee: "CONFIDENTIAL & RESTRICTED content is NEVER sent to commercial cloud LLMs.",
    inputFormat: "Security Metadata + Target Channels",
    outputFormat: "Authoritative PolicyDecision (Allow / Deny / Review)",
  },
  {
    id: "pgvector",
    name: "pgvector Storage",
    subtitle: "384d Vectors · Cosine Index",
    badge: "VEC",
    x: 530,
    y: 570,
    color: "#4f46e5",
    ringColor: "#6366f1",
    haloColor: "rgba(99, 102, 241, 0.22)",
    category: "vector",
    icon: Database,
    description: "Stores dense vector embeddings generated via all-MiniLM-L6-v2. Employs tenant and project-level isolation filters on every SQL query.",
    guarantee: "Row-level isolation. Vectors mapped 1-to-1 to chunk IDs.",
    inputFormat: "Chunk Text Batches",
    outputFormat: "Persisted Embeddings in PostgreSQL pgvector",
  },
  {
    id: "router",
    name: "Compliant Model Router",
    subtitle: "Local Air-Gapped / Cloud",
    badge: "RTR",
    x: 730,
    y: 140,
    color: "#7c3aed",
    ringColor: "#8b5cf6",
    haloColor: "rgba(139, 92, 246, 0.22)",
    category: "routing",
    icon: Cpu,
    description: "Routes LLM requests based strictly on PolicyRouter decision. Dispatches PUBLIC jobs to cloud endpoints; forces CONFIDENTIAL jobs to local air-gapped models.",
    guarantee: "Zero silent fallback to cloud for sensitive classifications.",
    inputFormat: "PolicyDecision + Generation Request",
    outputFormat: "Connected Provider (Local / Air-Gapped / Cloud)",
  },
  {
    id: "rag",
    name: "Semantic RAG Retrieval",
    subtitle: "Top-K Evidence · Scored",
    badge: "RAG",
    x: 730,
    y: 570,
    color: "#0891b2",
    ringColor: "#06b6d4",
    haloColor: "rgba(6, 182, 212, 0.22)",
    category: "vector",
    icon: Search,
    description: "Queries vector storage for high-similarity passages using task-aware queries. Surfaces exact chunk citations and relevance confidence scores.",
    guarantee: "If embeddings are missing, produces explicit insufficient-context; never fabricates.",
    inputFormat: "Target Query + Generation Context",
    outputFormat: "RAGContext (Citations, Excerpts, Relevance)",
  },
  {
    id: "intelligence",
    name: "Content Intelligence Hub",
    subtitle: "Canonical Facts · Brief",
    badge: "CI",
    x: 840,
    y: 360,
    color: "#0284c7",
    ringColor: "#38bdf8",
    haloColor: "rgba(56, 189, 248, 0.25)",
    category: "intelligence",
    icon: Cpu,
    description: "Extracts canonical entities, claims, key dates, statistics, and recommendations. Synthesizes a unified semantic brief that every downstream generator shares.",
    guarantee: "All facts validated against chunk IDs; hallucinated IDs discarded.",
    inputFormat: "RAGContext + Routed LLM Provider",
    outputFormat: "CanonicalContent Record + Shared Brief",
  },
  {
    id: "summary",
    name: "Executive Summary & Advisory",
    subtitle: "Grounded Policy Brief",
    badge: "SUM",
    x: 1040,
    y: 150,
    color: "#059669",
    ringColor: "#34d399",
    haloColor: "rgba(52, 211, 153, 0.2)",
    category: "output",
    icon: FileCheck2,
    description: "Generates concise, factual executive briefs and strategic decision-support advisories tailored to leadership density and communication objectives.",
    guarantee: "100% grounded assertions with traceable references.",
    inputFormat: "Shared Semantic Brief",
    outputFormat: "Structured Markdown + Summary Document",
  },
  {
    id: "pptx",
    name: "Presentation Deck",
    subtitle: "Structured PPTX Slides",
    badge: "PPT",
    x: 1040,
    y: 255,
    color: "#7c3aed",
    ringColor: "#a78bfa",
    haloColor: "rgba(167, 139, 250, 0.2)",
    category: "output",
    icon: Presentation,
    description: "Translates canonical points into a validated multi-slide structure rendered into an open-standard Microsoft PowerPoint (.pptx) presentation.",
    guarantee: "Deterministic Python-pptx rendering with no external cloud converter.",
    inputFormat: "PresentationStructure Schema",
    outputFormat: "Binary .pptx Presentation File",
  },
  {
    id: "infographic",
    name: "Visual Infographic",
    subtitle: "Rendered PNG / PDF",
    badge: "INF",
    x: 1040,
    y: 360,
    color: "#d97706",
    ringColor: "#fbbf24",
    haloColor: "rgba(251, 191, 36, 0.2)",
    category: "output",
    icon: ImageIcon,
    description: "Structures key metrics, callout stats, and takeaways into visual panels rendered directly as high-resolution infographic posters.",
    guarantee: "Verifiable metric badges matching extracted canonical stats.",
    inputFormat: "Infographic Layout Schema",
    outputFormat: "Rendered PNG Image & PDF Asset",
  },
  {
    id: "social",
    name: "Social Threads (LinkedIn & X)",
    subtitle: "Controlled Dissemination",
    badge: "SOC",
    x: 1040,
    y: 465,
    color: "#0284c7",
    ringColor: "#38bdf8",
    haloColor: "rgba(56, 189, 248, 0.2)",
    category: "output",
    icon: Share2,
    description: "Tailors policy communications for professional and public networks with character limits, tone calibration, and required policy tags.",
    guarantee: "Strict dissemination check prevents leaking restricted topics.",
    inputFormat: "Brief + Dissemination Rules",
    outputFormat: "LinkedIn Article + X Post Thread",
  },
  {
    id: "video",
    name: "Video Package & SRT",
    subtitle: "Timed Audio / Visual Cues",
    badge: "VID",
    x: 1040,
    y: 570,
    color: "#e11d48",
    ringColor: "#fb7185",
    haloColor: "rgba(251, 113, 133, 0.2)",
    category: "output",
    icon: Film,
    description: "Produces a production-ready video production package including voice-over narration scripts, visual scene descriptions, and timed SRT subtitle tracks.",
    guarantee: "Truthful cue generation without fabricated MP4 claims.",
    inputFormat: "VideoPackage Schema",
    outputFormat: "Director Storyboard PDF + Timed .SRT Subtitles",
  },
  {
    id: "provenance",
    name: "Verification & Provenance Seal",
    subtitle: "Ed25519 Signed · Audit Ledger",
    badge: "SEAL",
    x: 1220,
    y: 360,
    color: "#0891b2",
    ringColor: "#22d3ee",
    haloColor: "rgba(34, 211, 238, 0.28)",
    category: "provenance",
    icon: Fingerprint,
    description: "Validates claims against source evidence, seals every output artifact with a SHA-256 digest, and signs with an Ed25519 cryptographic private key.",
    guarantee: "Tamper-evident verification. Cryptographically verifiable lineage.",
    inputFormat: "All Completed Outputs + Verification Results",
    outputFormat: "Cryptographic Provenance Record + Ed25519 Digital Seal",
  },
];

const EDGES: WorkflowEdge[] = [
  // Source Ingest -> Perimeter Security
  {
    id: "e-src-sec",
    from: "source",
    to: "security",
    path: "M 100 360 C 180 360, 240 190, 320 190",
    badge: "Raw Document",
    lineStyle: "dashed",
    color: "#3b82f6",
    particleColor: "#2563eb",
    category: "security",
    speed: 2.8,
  },
  // Source Ingest -> Deterministic Chunker
  {
    id: "e-src-chk",
    from: "source",
    to: "chunker",
    path: "M 100 360 C 180 360, 240 530, 320 530",
    badge: "Normalized Text",
    lineStyle: "solid",
    color: "#2563eb",
    particleColor: "#60a5fa",
    category: "rag",
    speed: 3.0,
  },
  // Perimeter Security -> Policy Engine
  {
    id: "e-sec-pol",
    from: "security",
    to: "policy",
    path: "M 320 190 C 400 190, 450 140, 530 140",
    badge: "Clean Stream",
    lineStyle: "dashed",
    color: "#f59e0b",
    particleColor: "#d97706",
    category: "security",
    speed: 2.4,
  },
  // Policy Engine -> Compliant Router
  {
    id: "e-pol-rtr",
    from: "policy",
    to: "router",
    path: "M 530 140 C 600 140, 660 140, 730 140",
    badge: "Route Decision",
    lineStyle: "solid",
    color: "#10b981",
    particleColor: "#059669",
    category: "security",
    speed: 2.2,
  },
  // Deterministic Chunker -> pgvector
  {
    id: "e-chk-vec",
    from: "chunker",
    to: "pgvector",
    path: "M 320 530 C 400 530, 450 570, 530 570",
    badge: "UUID Chunks",
    lineStyle: "solid",
    color: "#6366f1",
    particleColor: "#4f46e5",
    category: "rag",
    speed: 2.5,
  },
  // pgvector -> Semantic RAG
  {
    id: "e-vec-rag",
    from: "pgvector",
    to: "rag",
    path: "M 530 570 C 600 570, 660 570, 730 570",
    badge: "384d Embeddings",
    lineStyle: "dashed",
    color: "#06b6d4",
    particleColor: "#0891b2",
    category: "rag",
    speed: 2.2,
  },
  // Compliant Router -> Content Intelligence
  {
    id: "e-rtr-ci",
    from: "router",
    to: "intelligence",
    path: "M 730 140 C 790 140, 800 360, 840 360",
    badge: "Compliant LLM",
    lineStyle: "solid",
    color: "#8b5cf6",
    particleColor: "#7c3aed",
    category: "transformation",
    speed: 3.2,
  },
  // Semantic RAG -> Content Intelligence
  {
    id: "e-rag-ci",
    from: "rag",
    to: "intelligence",
    path: "M 730 570 C 790 570, 800 360, 840 360",
    badge: "Top-5 Evidence",
    lineStyle: "solid",
    color: "#06b6d4",
    particleColor: "#0284c7",
    category: "rag",
    speed: 3.2,
  },
  // Content Intelligence -> Executive Summary
  {
    id: "e-ci-sum",
    from: "intelligence",
    to: "summary",
    path: "M 840 360 C 920 360, 960 150, 1040 150",
    badge: "Briefing Brief",
    lineStyle: "dashed",
    color: "#10b981",
    particleColor: "#059669",
    category: "transformation",
    speed: 2.8,
  },
  // Content Intelligence -> PPTX Deck
  {
    id: "e-ci-ppt",
    from: "intelligence",
    to: "pptx",
    path: "M 840 360 C 920 360, 960 255, 1040 255",
    badge: "Slide Outline",
    lineStyle: "solid",
    color: "#8b5cf6",
    particleColor: "#7c3aed",
    category: "transformation",
    speed: 2.6,
  },
  // Content Intelligence -> Infographic
  {
    id: "e-ci-inf",
    from: "intelligence",
    to: "infographic",
    path: "M 840 360 C 920 360, 960 360, 1040 360",
    badge: "Data Matrix",
    lineStyle: "solid",
    color: "#f59e0b",
    particleColor: "#d97706",
    category: "transformation",
    speed: 2.5,
  },
  // Content Intelligence -> Social Threads
  {
    id: "e-ci-soc",
    from: "intelligence",
    to: "social",
    path: "M 840 360 C 920 360, 960 465, 1040 465",
    badge: "Post Excerpts",
    lineStyle: "dashed",
    color: "#38bdf8",
    particleColor: "#0284c7",
    category: "transformation",
    speed: 2.7,
  },
  // Content Intelligence -> Video Storyboard
  {
    id: "e-ci-vid",
    from: "intelligence",
    to: "video",
    path: "M 840 360 C 920 360, 960 570, 1040 570",
    badge: "Cues & Narration",
    lineStyle: "solid",
    color: "#f43f5e",
    particleColor: "#e11d48",
    category: "transformation",
    speed: 2.9,
  },
  // Executive Summary -> Provenance Seal
  {
    id: "e-sum-prov",
    from: "summary",
    to: "provenance",
    path: "M 1040 150 C 1110 150, 1150 360, 1220 360",
    badge: "Verified Summary",
    lineStyle: "dashed",
    color: "#10b981",
    particleColor: "#059669",
    category: "provenance",
    speed: 3.0,
  },
  // PPTX Deck -> Provenance Seal
  {
    id: "e-ppt-prov",
    from: "pptx",
    to: "provenance",
    path: "M 1040 255 C 1110 255, 1150 360, 1220 360",
    badge: "Signed PPTX",
    lineStyle: "solid",
    color: "#8b5cf6",
    particleColor: "#7c3aed",
    category: "provenance",
    speed: 2.8,
  },
  // Infographic -> Provenance Seal
  {
    id: "e-inf-prov",
    from: "infographic",
    to: "provenance",
    path: "M 1040 360 C 1110 360, 1150 360, 1220 360",
    badge: "Signed Image",
    lineStyle: "solid",
    color: "#f59e0b",
    particleColor: "#d97706",
    category: "provenance",
    speed: 2.6,
  },
  // Social Threads -> Provenance Seal
  {
    id: "e-soc-prov",
    from: "social",
    to: "provenance",
    path: "M 1040 465 C 1110 465, 1150 360, 1220 360",
    badge: "Signed Thread",
    lineStyle: "dashed",
    color: "#38bdf8",
    particleColor: "#0284c7",
    category: "provenance",
    speed: 2.9,
  },
  // Video Storyboard -> Provenance Seal
  {
    id: "e-vid-prov",
    from: "video",
    to: "provenance",
    path: "M 1040 570 C 1110 570, 1150 360, 1220 360",
    badge: "Signed SRT",
    lineStyle: "solid",
    color: "#f43f5e",
    particleColor: "#e11d48",
    category: "provenance",
    speed: 3.1,
  },
];

// Helper to compute midpoint of cubic bezier path M x0,y0 C cx1,cy1, cx2,cy2, x1,y1
function getCubicBezierMidpoint(pathStr: string): { x: number; y: number } {
  const match = pathStr.match(
    /M\s*(-?\d+\.?\d*)\s+(-?\d+\.?\d*)\s+C\s*(-?\d+\.?\d*)\s+(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)[,\s]+(-?\d+\.?\d*)\s+(-?\d+\.?\d*)/
  );
  if (!match) return { x: 0, y: 0 };
  const [, x0, y0, cx1, cy1, cx2, cy2, x1, y1] = match.map(Number);
  // t = 0.5 for midpoint
  const t = 0.5;
  const mt = 1 - t;
  const mx =
    mt * mt * mt * x0 +
    3 * mt * mt * t * cx1 +
    3 * mt * t * t * cx2 +
    t * t * t * x1;
  const my =
    mt * mt * mt * y0 +
    3 * mt * mt * t * cy1 +
    3 * mt * t * t * cy2 +
    t * t * t * y1;
  return { x: mx, y: my };
}

export interface WorkflowGraphAnimationProps {
  initialTheme?: "light" | "dark";
  showInspectorByDefault?: boolean;
  authMode?: boolean;
}

export function WorkflowGraphAnimation({
  initialTheme,
  showInspectorByDefault = false,
  authMode = false,
}: WorkflowGraphAnimationProps) {
  const { resolved } = useTheme();
  // Automatically follows global application appearance (resolved: light or dark)
  // while still honoring explicit initialTheme prop for isolated tests or embeds.
  const theme: "light" | "dark" =
    initialTheme ??
    resolved ??
    (typeof document !== "undefined" && !document.documentElement.classList.contains("dark")
      ? "light"
      : "dark");

  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  // In authMode (sign in / register), animation is always on
  const effectiveIsPlaying = authMode ? true : isPlaying;
  const speedMultiplier = 1; // Locked to 1x by default (speed selector removed)
  const [filter, setFilter] = useState<FilterCategory>("all");
  const [selectedNode, setSelectedNode] = useState<WorkflowNode | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [isFullscreen, setIsFullscreen] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  // Play/Pause effect
  useEffect(() => {
    if (!svgRef.current) return;
    try {
      if (effectiveIsPlaying) {
        svgRef.current.unpauseAnimations();
      } else {
        svgRef.current.pauseAnimations();
      }
    } catch {
      // Best-effort in browsers that support SVG animation controls
    }
  }, [effectiveIsPlaying]);

  // Filtered edges
  const visibleEdges = useMemo(() => {
    return EDGES.filter((edge) => {
      if (filter === "all") return true;
      if (filter === "security") return edge.category === "security";
      if (filter === "rag") return edge.category === "rag";
      if (filter === "transformation") return edge.category === "transformation";
      if (filter === "provenance") return edge.category === "provenance";
      return true;
    });
  }, [filter]);

  // Determine active/highlighted nodes based on filter or hover
  const activeNodeIds = useMemo(() => {
    const ids = new Set<string>();
    visibleEdges.forEach((e) => {
      ids.add(e.from);
      ids.add(e.to);
    });
    return ids;
  }, [visibleEdges]);

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  };

  const isLight = theme === "light";
  const bgColor = isLight ? "#ffffff" : "#0a0f1d";
  const dotColor = isLight ? "#e2e8f0" : "#1e293b";
  const cardBg = isLight ? "#ffffff" : "#111827";
  const cardBorder = isLight ? "#e2e8f0" : "#1f2937";
  const textPrimary = isLight ? "#0f172a" : "#f8fafc";
  const textMuted = isLight ? "#64748b" : "#94a3b8";
  const pillBg = isLight ? "#ffffff" : "#182234";
  const pillBorder = isLight ? "#cbd5e1" : "#334155";
  const pillText = isLight ? "#1e293b" : "#e2e8f0";

  return (
    <div
      ref={containerRef}
      className={`relative w-full ${
        authMode ? "h-full flex flex-col justify-between" : "rounded-2xl border shadow-2xl"
      } overflow-hidden transition-colors duration-300 font-sans ${
        isLight ? "border-slate-200 text-slate-900" : "border-slate-800 text-slate-100"
      }`}
      style={{ backgroundColor: bgColor }}
    >
      {/* Top Interactive Toolbar */}
      <div
        className={`px-3 py-2 sm:px-4 sm:py-2.5 flex flex-wrap items-center justify-between gap-2 border-b backdrop-blur-md transition-colors ${
          isLight
            ? "border-slate-200/80 bg-white/95"
            : "border-slate-800/80 bg-slate-950/80"
        }`}
      >

        {/* Left: Branding & Status Indicator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center h-8 w-8 rounded-lg bg-primary/10 text-primary border border-primary/20">
            <Layers className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xs sm:text-sm font-semibold tracking-tight uppercase" style={{ color: textPrimary }}>
                KaryaSetu AI · Workflow Stream Animation
              </h2>
              <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium uppercase bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                Live Pulse
              </span>
            </div>
            <p className="text-[11px]" style={{ color: textMuted }}>
              Deterministic data packet transit across policy-bounded pipeline stages
            </p>
          </div>
        </div>

        {/* Center: Stage Filter Pill Tabs */}
        <div className="flex items-center gap-1 p-1 rounded-lg border bg-opacity-50" style={{ borderColor: cardBorder, backgroundColor: isLight ? "#f1f5f9" : "#0f172a" }}>
          {[
            { id: "all", label: "All Flows" },
            { id: "security", label: "Security & Policy" },
            { id: "rag", label: "RAG Grounding" },
            { id: "transformation", label: "Outputs" },
            { id: "provenance", label: "Provenance Seal" },
          ].map((item) => (
            <button
              key={item.id}
              onClick={() => setFilter(item.id as FilterCategory)}
              className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-all ${
                filter === item.id
                  ? "bg-blue-600 text-white shadow-sm"
                  : isLight
                  ? "text-slate-600 hover:text-slate-900 hover:bg-slate-200/60"
                  : "text-slate-400 hover:text-slate-100 hover:bg-slate-800"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        {/* Right Controls: Play/Pause, Fullscreen */}
        <div className="flex items-center gap-2">
          {/* Play/Pause Button (omitted in authMode where animation is always on) */}
          {!authMode && (
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className={`p-2 rounded-lg border transition-all flex items-center gap-1.5 text-xs font-medium ${
                isLight
                  ? "border-slate-200 bg-white hover:bg-slate-100 text-slate-700"
                  : "border-slate-800 bg-slate-900 hover:bg-slate-800 text-slate-200"
              }`}
              title={isPlaying ? "Pause stream animation" : "Resume stream animation"}
            >
              {isPlaying ? <Pause className="h-3.5 w-3.5 text-amber-500" /> : <Play className="h-3.5 w-3.5 text-emerald-500" />}
              <span className="hidden sm:inline">{isPlaying ? "Pause" : "Play"}</span>
            </button>
          )}

          {/* Fullscreen Toggle Button */}
          <button
            onClick={toggleFullscreen}
            className={`p-2 rounded-lg border transition-colors ${
              isLight
                ? "border-slate-200 bg-white hover:bg-slate-100 text-slate-700"
                : "border-slate-800 bg-slate-900 hover:bg-slate-800 text-slate-200"
            }`}
            title="Toggle Fullscreen"
          >
            {isFullscreen ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>

      {/* Main SVG Canvas Viewport */}
      <div
        className={`relative w-full select-none ${
          authMode
            ? "flex-1 min-h-0 flex items-center justify-center overflow-hidden"
            : "overflow-x-auto"
        }`}
      >
        <svg
          ref={svgRef}
          viewBox="0 0 1340 720"
          className={
            authMode
              ? "w-full h-full max-h-full block select-none object-contain"
              : "w-full h-auto min-w-[1000px] block"
          }
          preserveAspectRatio="xMidYMid meet"
          style={{
            maxHeight: authMode
              ? "100%"
              : isFullscreen
              ? "calc(100vh - 120px)"
              : "720px",
          }}
        >
          <defs>
            {/* Dot Grid Background Pattern */}
            <pattern id="dot-grid" x="0" y="0" width="24" height="24" patternUnits="userSpaceOnUse">
              <circle cx="12" cy="12" r="0.75" fill={dotColor} opacity={0.6} />
            </pattern>

            {/* Restrained enterprise diffusion filter for particles */}
            <filter id="particle-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="1.2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Restrained halo glow for selected nodes */}
            <filter id="halo-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>

            {/* Pill Drop Shadow */}
            <filter id="pill-shadow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="1.5" stdDeviation="2" floodOpacity={isLight ? "0.08" : "0.35"} floodColor="#000000" />
            </filter>
          </defs>

          {/* Background Dot Grid Layer */}
          <rect width="1340" height="720" fill="url(#dot-grid)" />

          {/* Stage 1: Render All Connecting Lines / Paths */}
          <g id="workflow-edges">
            {visibleEdges.map((edge) => {
              const isEdgeHighlighted =
                hoveredNodeId === edge.from ||
                hoveredNodeId === edge.to ||
                selectedNode?.id === edge.from ||
                selectedNode?.id === edge.to;

              const strokeColor = isEdgeHighlighted
                ? edge.color
                : isLight
                ? edge.color
                : edge.color;

              const strokeOpacity = isEdgeHighlighted
                ? 1
                : isLight
                ? 0.55
                : 0.45;

              const strokeWidth = isEdgeHighlighted ? 3 : 2;

              const strokeDasharray =
                edge.lineStyle === "dashed"
                  ? "7 5"
                  : edge.lineStyle === "dotted"
                  ? "3 3"
                  : undefined;

              return (
                <g key={edge.id} className="transition-all duration-300">
                  {/* Base Track Path */}
                  <path
                    id={edge.id}
                    d={edge.path}
                    fill="none"
                    stroke={strokeColor}
                    strokeWidth={strokeWidth}
                    strokeDasharray={strokeDasharray}
                    strokeOpacity={strokeOpacity}
                    strokeLinecap="round"
                  />

                  {/* MOVING DATA PACKET PARTICLES (Traveling along the path) */}
                  {isPlaying && (
                    <>
                      {/* Particle 1: Main Head with Subtle Aura */}
                      <circle
                        r={4.5}
                        fill={edge.particleColor}
                        opacity={0.2}
                      >
                        <animateMotion
                          dur={`${edge.speed / speedMultiplier}s`}
                          repeatCount="indefinite"
                          rotate="auto"
                        >
                          <mpath href={`#${edge.id}`} />
                        </animateMotion>
                      </circle>
                      <circle
                        r={2.8}
                        fill={edge.particleColor}
                        filter="url(#particle-glow)"
                      >
                        <animateMotion
                          dur={`${edge.speed / speedMultiplier}s`}
                          repeatCount="indefinite"
                          rotate="auto"
                        >
                          <mpath href={`#${edge.id}`} />
                        </animateMotion>
                      </circle>
                      <circle
                        r={1.2}
                        fill="#ffffff"
                      >
                        <animateMotion
                          dur={`${edge.speed / speedMultiplier}s`}
                          repeatCount="indefinite"
                          rotate="auto"
                        >
                          <mpath href={`#${edge.id}`} />
                        </animateMotion>
                      </circle>

                      {/* Particle 2: Follower for continuous flow illusion */}
                      <circle
                        r={3.8}
                        fill={edge.particleColor}
                        opacity={0.15}
                      >
                        <animateMotion
                          dur={`${edge.speed / speedMultiplier}s`}
                          repeatCount="indefinite"
                          begin={`${(edge.speed / speedMultiplier) * 0.5}s`}
                          keyPoints="0;1"
                          keyTimes="0;1"
                          calcMode="linear"
                        >
                          <mpath href={`#${edge.id}`} />
                        </animateMotion>
                      </circle>
                      <circle
                        r={2.2}
                        fill={isLight ? "#ffffff" : "#f8fafc"}
                        stroke={edge.particleColor}
                        strokeWidth={1.2}
                      >
                        <animateMotion
                          dur={`${edge.speed / speedMultiplier}s`}
                          repeatCount="indefinite"
                          begin={`${(edge.speed / speedMultiplier) * 0.5}s`}
                          keyPoints="0;1"
                          keyTimes="0;1"
                          calcMode="linear"
                        >
                          <mpath href={`#${edge.id}`} />
                        </animateMotion>
                      </circle>
                    </>
                  )}

                  {/* Pill Badge along the path (like the currency badges in the reference image) */}
                  {(() => {
                    const mid = getCubicBezierMidpoint(edge.path);
                    const pillWidth = Math.max(76, edge.badge.length * 6.5 + 20);
                    const pillHeight = 22;
                    return (
                      <g
                        transform={`translate(${mid.x}, ${mid.y})`}
                        className="pointer-events-none"
                      >
                        <rect
                          x={-pillWidth / 2}
                          y={-pillHeight / 2}
                          width={pillWidth}
                          height={pillHeight}
                          rx={pillHeight / 2}
                          fill={pillBg}
                          stroke={pillBorder}
                          strokeWidth={1.2}
                          filter="url(#pill-shadow)"
                        />
                        <text
                          x={0}
                          y={3.5}
                          textAnchor="middle"
                          fill={pillText}
                          fontSize="9.5"
                          fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
                          fontWeight="600"
                          letterSpacing="0.02em"
                        >
                          {edge.badge}
                        </text>
                      </g>
                    );
                  })()}
                </g>
              );
            })}
          </g>

          {/* Stage 2: Render All Nodes */}
          <g id="workflow-nodes">
            {NODES.map((node) => {
              const isSelected = selectedNode?.id === node.id;
              const isHovered = hoveredNodeId === node.id;
              const isDimmed =
                filter !== "all" && !activeNodeIds.has(node.id);

              return (
                <g
                  key={node.id}
                  transform={`translate(${node.x}, ${node.y})`}
                  className={`cursor-pointer transition-all duration-300 ${
                    isDimmed ? "opacity-30" : "opacity-100"
                  }`}
                  onClick={() => setSelectedNode(node)}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                >
                  {/* Outer Pulsing Glow Halo Ring (Matching Reference Image) */}
                  <circle
                    r={isSelected || isHovered ? 38 : 32}
                    fill={node.haloColor}
                    filter="url(#halo-glow)"
                    className="transition-all duration-300"
                  />

                  {/* Concentric Subtle Border Ring */}
                  <circle
                    r={26}
                    fill="none"
                    stroke={node.ringColor}
                    strokeWidth={1.2}
                    strokeDasharray="4 4"
                    opacity={0.65}
                  />

                  {/* Core Node Circle */}
                  <circle
                    r={20}
                    fill={isLight ? "#ffffff" : "#0f172a"}
                    stroke={node.color}
                    strokeWidth={isSelected || isHovered ? 3.5 : 2.5}
                    className="transition-all duration-200"
                  />

                  {/* Center Monogram / Monospace Badge inside the circle */}
                  <text
                    x={0}
                    y={4.5}
                    textAnchor="middle"
                    fill={node.color}
                    fontSize="10"
                    fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
                    fontWeight="700"
                    letterSpacing="0.05em"
                  >
                    {node.badge}
                  </text>

                  {/* Primary Node Label (Below the node) */}
                  <text
                    x={0}
                    y={38}
                    textAnchor="middle"
                    fill={textPrimary}
                    fontSize="11.5"
                    fontWeight="700"
                    fontFamily="inherit"
                    className="tracking-tight"
                  >
                    {node.name}
                  </text>

                  {/* Subtitle / Metadata below node (matching address/crypto tags in reference image) */}
                  <text
                    x={0}
                    y={51}
                    textAnchor="middle"
                    fill={textMuted}
                    fontSize="9"
                    fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace"
                    fontWeight="500"
                    letterSpacing="0.01em"
                  >
                    {node.subtitle}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>

        {/* Floating Quick Hint overlay */}
        <div
          className="absolute bottom-2 left-3 px-2.5 py-1 rounded-lg border text-[10.5px] font-mono flex items-center gap-1.5 backdrop-blur-sm shadow-sm pointer-events-none"
          style={{
            backgroundColor: isLight ? "rgba(255,255,255,0.9)" : "rgba(15,23,42,0.9)",
            borderColor: cardBorder,
            color: textMuted,
          }}
        >
          <Info className="h-3 w-3 text-blue-500" />
          <span>Click any node to inspect role &amp; guarantees</span>
        </div>
      </div>

      {/* Interactive Node Inspector Modal Pop-up (Centered overlay, zero layout shifting) */}
      {selectedNode && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-slate-900/40 backdrop-blur-sm animate-in fade-in duration-200"
          onClick={() => setSelectedNode(null)}
        >
          <div
            className={`relative w-full max-w-md sm:max-w-lg rounded-2xl p-5 sm:p-6 shadow-2xl border transition-all animate-in zoom-in-95 duration-200 ${
              isLight
                ? "bg-white border-slate-200 text-slate-900 shadow-slate-300/50"
                : "bg-slate-900 border-slate-800 text-slate-100 shadow-black/80"
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Close Button */}
            <button
              onClick={() => setSelectedNode(null)}
              className={`absolute top-4 right-4 px-2.5 py-1 rounded-lg border text-xs font-medium flex items-center gap-1 transition-colors ${
                isLight
                  ? "border-slate-200 hover:bg-slate-100 text-slate-600 hover:text-slate-900"
                  : "border-slate-700 hover:bg-slate-800 text-slate-300 hover:text-slate-100"
              }`}
              aria-label="Close inspector"
            >
              <span>Close Inspector ✕</span>
            </button>

            {/* Header */}
            <div className="flex items-center gap-3 mb-4 pr-8">
              <div
                className="h-11 w-11 rounded-xl flex items-center justify-center font-mono font-bold text-sm shadow-sm border shrink-0"
                style={{
                  backgroundColor: isLight ? "#ffffff" : "#0f172a",
                  borderColor: selectedNode.color,
                  color: selectedNode.color,
                }}
              >
                {selectedNode.badge}
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-base font-bold tracking-tight" style={{ color: textPrimary }}>
                    {selectedNode.name}
                  </h3>
                  <span
                    className="px-2 py-0.5 rounded text-[10px] font-mono uppercase font-semibold"
                    style={{
                      backgroundColor: `${selectedNode.color}15`,
                      color: selectedNode.color,
                      border: `1px solid ${selectedNode.color}30`,
                    }}
                  >
                    {selectedNode.category}
                  </span>
                </div>
                <p className="text-xs font-mono" style={{ color: textMuted }}>
                  {selectedNode.subtitle}
                </p>
              </div>
            </div>

            {/* Content Cards */}
            <div className="space-y-3 text-xs">
              {/* Architectural Role */}
              <div
                className="p-3 rounded-xl border"
                style={{ borderColor: cardBorder, backgroundColor: isLight ? "#f8fafc" : "#0b1324" }}
              >
                <span className="font-mono text-[10px] uppercase font-semibold text-blue-600 dark:text-blue-400 block mb-1">
                  Architectural Role
                </span>
                <p className="leading-relaxed" style={{ color: textPrimary }}>
                  {selectedNode.description}
                </p>
              </div>

              {/* Zero-Trust Guarantee */}
              <div className="p-3 rounded-xl border border-emerald-500/20 bg-emerald-500/5">
                <span className="font-mono text-[10px] uppercase font-semibold text-emerald-600 dark:text-emerald-400 block mb-1">
                  Zero-Trust Guarantee
                </span>
                <div className="flex items-start gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                  <p className="leading-relaxed font-medium" style={{ color: textPrimary }}>
                    {selectedNode.guarantee}
                  </p>
                </div>
              </div>

              {/* Data Contracts */}
              <div>
                <span className="font-mono text-[10px] uppercase font-semibold text-purple-600 dark:text-purple-400 block mb-1">
                  Data Stream Contract
                </span>
                <div className="grid grid-cols-2 gap-2">
                <div
                  className="p-2.5 rounded-xl border font-mono text-[11px]"
                  style={{ borderColor: cardBorder, backgroundColor: isLight ? "#f8fafc" : "#0b1324" }}
                >
                  <span className="text-[10px] text-slate-400 block mb-0.5">IN FORMAT</span>
                  <span className="font-semibold" style={{ color: textPrimary }}>{selectedNode.inputFormat}</span>
                </div>
                <div
                  className="p-2.5 rounded-xl border font-mono text-[11px]"
                  style={{ borderColor: cardBorder, backgroundColor: isLight ? "#f8fafc" : "#0b1324" }}
                >
                  <span className="text-[10px] text-slate-400 block mb-0.5">OUT FORMAT</span>
                  <span className="font-semibold" style={{ color: textPrimary }}>{selectedNode.outputFormat}</span>
                </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
