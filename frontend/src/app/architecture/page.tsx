/**
 * KaryaSetu AI — Architecture Demo Animation Page.
 *
 * Provides a dedicated, high-assurance browser-based presentation viewport
 * for the 35–40 second deterministic architecture animation sequence.
 * Fully recordable for technical evaluation.
 */
"use client";

import { useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout";
import { ArchitectureDemo } from "@/components/demo/ArchitectureDemo";
import { ShieldCheck, Video, Info, Maximize2, ArrowRight, ExternalLink } from "lucide-react";

export default function ArchitectureDemoPage() {
  const [fullscreenMode, setFullscreenMode] = useState(false);

  if (fullscreenMode) {
    return (
      <div className="min-h-screen bg-surface-container-lowest text-foreground flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant/30 bg-surface-container/60 backdrop-blur text-xs">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-primary" />
            <span className="font-mono uppercase font-medium text-primary">KaryaSetu AI · Architecture Visualization</span>
          </div>
          <button
            onClick={() => setFullscreenMode(false)}
            className="px-2.5 py-1 rounded bg-surface-container-high hover:bg-surface-container-highest text-muted-foreground hover:text-foreground text-xs font-mono transition-colors"
          >
            Exit Theater Mode (Esc)
          </button>
        </div>
        <div className="flex-1 p-4 md:p-8 flex items-center justify-center">
          <div className="w-full max-w-7xl">
            <ArchitectureDemo />
          </div>
        </div>
      </div>
    );
  }

  return (
    <AppShell
      active="/architecture"
      title="Architecture Demo"
      subtitle="35–40s deterministic visual sequence demonstrating the zero-trust pipeline"
    >
      <div className="space-y-6 pb-12">
        {/* Page Header Bar */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="label-mono-xs uppercase text-secondary-fixed-dim">
                Enterprise Architecture · Live Demo
              </span>
              <span className="h-1.5 w-1.5 rounded-full bg-secondary animate-pulse" />
            </div>
            <h1 className="headline-xl font-semibold text-foreground tracking-tight">
              Architecture Demo Animation
            </h1>
            <p className="text-sm text-muted-foreground max-w-3xl leading-relaxed">
              Real-time browser-rendered 38-second deterministic narrative demonstrating how a single trusted
              source document traverses zero-trust ingestion, policy routing, RAG grounding, multi-format transformation,
              human-in-the-loop verification, and cryptographic artifact signing.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => setFullscreenMode(true)}
              className="inline-flex items-center gap-2 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
            >
              <Maximize2 className="h-3.5 w-3.5" />
              <span>Launch Theater View</span>
            </button>
            <div className="flex items-center gap-1.5 rounded bg-surface-container-high px-2.5 py-1.5 text-xs text-on-surface">
              <ShieldCheck className="h-3.5 w-3.5 text-secondary" />
              <span className="font-label-mono-sm uppercase">Zero Fake Metrics</span>
            </div>
          </div>
        </div>

        {/* Demo Animation Component Viewport */}
        <div className="rounded-xl border border-outline-variant/50 shadow-2xl overflow-hidden bg-surface-container-lowest">
          <ArchitectureDemo />
        </div>

        {/* Evaluation Technical Explanatory Notes */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-8">
          <div className="p-4 rounded-lg border border-outline-variant/40 bg-surface-container-low">
            <div className="flex items-center gap-2 mb-2">
              <span className="h-2 w-2 rounded-full bg-primary" />
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-foreground">
                Scene 1–2: Ingestion
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Authoritative document anchored with SHA-256 hash. Enters perimeter screening (ClamAV, prompt injection scanner, DLP redaction, and strict classification).
            </p>
          </div>

          <div className="p-4 rounded-lg border border-outline-variant/40 bg-surface-container-low">
            <div className="flex items-center gap-2 mb-2">
              <span className="h-2 w-2 rounded-full bg-amber-400" />
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-foreground">
                Scene 3–4: Policy & RAG
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Deterministic policy routing selects permitted execution route (Cloud, Local, or Air-Gapped/Offline). Evidence chunks bound with source offset citations.
            </p>
          </div>

          <div className="p-4 rounded-lg border border-outline-variant/40 bg-surface-container-low">
            <div className="flex items-center gap-2 mb-2">
              <span className="h-2 w-2 rounded-full bg-emerald-400" />
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-foreground">
                Scene 5: 7 Output Types
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Branches into Summary, Advisory, Presentation (PPTX), LinkedIn, X Thread, Infographic, and structured Video Package (storyboard + SRT cues; no fake MP4).
            </p>
          </div>

          <div className="p-4 rounded-lg border border-outline-variant/40 bg-surface-container-low">
            <div className="flex items-center gap-2 mb-2">
              <span className="h-2 w-2 rounded-full bg-cyan-400" />
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-foreground">
                Scene 6–8: Release & Seal
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              Automated verification gates, mandatory human approval, policy supremacy hard-blocks, tamper-evident SHA-256 seal, and Ed25519 digital signature.
            </p>
          </div>
        </div>

        {/* Recording Guidelines for Demo Video */}
        <div className="rounded-lg border border-outline-variant/40 bg-surface-container-lowest p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded bg-primary/10 flex items-center justify-center text-primary shrink-0">
              <Video className="h-4 w-4" />
            </div>
            <div>
              <h4 className="text-xs font-semibold text-foreground">Screen Recording Ready</h4>
              <p className="text-xs text-muted-foreground">
                Use the &quot;Clean Record Mode&quot; (eye icon) or Fullscreen button to hide control chrome during OBS/browser capture.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <Link
              href="/security"
              className="inline-flex items-center gap-1.5 text-xs text-primary hover:underline font-medium"
            >
              <span>View Security &amp; Integrity Console</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
