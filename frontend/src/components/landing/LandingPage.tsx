/**
 * KaryaSetu AI — Public Enterprise Landing Page.
 *
 * Presented to unauthenticated users before entering the protected workspace.
 * Factual capabilities, zero fabricated claims or metrics.
 */
"use client";

import Link from "next/link";
import {
  FileText,
  ShieldCheck,
  CheckCircle2,
  ArrowRight,
  Layers,
  FileCheck2,
  Lock,
} from "lucide-react";
import { LogoMark } from "@/components/brand";
import { ArchitectureDemo } from "@/components/demo/ArchitectureDemo";
import { LaptopMockup } from "@/components/landing/LaptopMockup";

export function LandingPage() {
  return (
    <div className="min-h-screen bg-background text-foreground selection:bg-primary/20 selection:text-primary">
      {/* Top navigation bar */}
      <header className="sticky top-0 z-50 border-b border-border/80 bg-background/90 backdrop-blur-md">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <LogoMark size={30} />
            <div className="flex flex-col">
              <span className="font-semibold tracking-tight text-foreground text-sm">
                KaryaSetu AI
              </span>
              <span className="label-mono-xs text-[10px] uppercase text-muted-foreground">
                Policy-Aware Information Transformation
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="rounded px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              Sign in
            </Link>
            <Link
              href="/register"
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3.5 py-1.5 text-sm font-medium text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
            >
              Create account
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>
      </header>

      {/* Hero section */}
      <main>
        <section className="relative z-10 overflow-hidden py-16 sm:py-24 lg:py-28">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-3xl text-center">
              <div className="inline-flex items-center gap-2 rounded border border-primary/25 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
                <ShieldCheck className="h-3.5 w-3.5" />
                <span>Policy-Controlled Information Transformation</span>
              </div>

              <h1 className="mt-6 text-3xl font-bold tracking-tight text-foreground sm:text-4xl lg:text-5xl">
                One trusted source.{" "}
                <span className="text-primary">
                  Multiple audience-ready artifacts.
                </span>
              </h1>

              <p className="mt-5 text-base sm:text-lg leading-relaxed text-muted-foreground">
                KaryaSetu AI bridges authoritative documents with cross-channel
                communications. Ingest institutional source material once and
                generate grounded executive advisories, policy briefs, and structured
                summaries with verifiable provenance.
              </p>

              <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 rounded-md bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90"
                >
                  Enter KaryaSetu
                  <ArrowRight className="h-4 w-4" />
                </Link>
                <Link
                  href="/register"
                  className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-5 py-2.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-muted"
                >
                  Create Account
                </Link>
              </div>

              <div className="mt-8 flex items-center justify-center gap-6 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  <Lock className="h-3.5 w-3.5 text-primary" />
                  Isolated Project Tenancy
                </span>
                <span className="flex items-center gap-1.5">
                  <ShieldCheck className="h-3.5 w-3.5 text-primary" />
                  Deterministic Grounding
                </span>
                <span className="flex items-center gap-1.5">
                  <CheckCircle2 className="h-3.5 w-3.5 text-primary" />
                  Verified Evidence
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Architecture Demo — Realistic MacBook Pro Showcase */}
        <section className="relative py-10 md:py-16 border-t border-border/60 bg-background overflow-hidden">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-3xl text-center mb-8 sm:mb-12">
              <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-primary/10 border border-primary/20 text-xs font-mono font-semibold text-primary mb-3">
                <span className="w-1.5 h-1.5 rounded-full bg-primary" />
                INTERACTIVE ARCHITECTURE SHOWCASE
              </div>
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-foreground">
                See KaryaSetu AI in Action
              </h2>
              <p className="mt-2.5 text-sm sm:text-base text-muted-foreground leading-relaxed max-w-2xl mx-auto">
                Watch how authoritative source documents are securely ingested, governed by policy,
                grounded in evidence, and transformed into 7 verifiable deliverables.
              </p>
            </div>

            {/* Laptop Mockup Container */}
            <div className="w-full flex justify-center">
              <LaptopMockup>
                <ArchitectureDemo mode="landing" speed={2} />
              </LaptopMockup>
            </div>
          </div>
        </section>

        {/* 3 Core Factual Capabilities */}
        <section className="border-t border-border bg-muted/20 py-16 sm:py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
                Engineered for High-Stakes Transformation
              </h2>
              <p className="mt-2.5 text-sm text-muted-foreground">
                Built specifically to convert complex institutional materials into
                tailored communications without hallucinations or context drift.
              </p>
            </div>

            <div className="mt-10 grid grid-cols-1 gap-6 md:grid-cols-3">
              {/* Capability 1 */}
              <div className="flex flex-col rounded-lg border border-border bg-card p-6 shadow-sm transition-colors hover:border-primary/40">
                <div className="flex h-9 w-9 items-center justify-center rounded bg-primary/10 text-primary">
                  <Layers className="h-4 w-4" />
                </div>
                <h3 className="mt-4 text-sm font-semibold text-foreground">
                  Multi-Format Output Generation
                </h3>
                <p className="mt-2 flex-1 text-xs sm:text-sm text-muted-foreground leading-relaxed">
                  Orchestrate simultaneous generation of executive briefs,
                  strategic advisories, presentation outlines, and public-facing
                  bulletins from a single authoritative source file.
                </p>
                <div className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                  Configurable tone, audience level, and detail density.
                </div>
              </div>

              {/* Capability 2 */}
              <div className="flex flex-col rounded-lg border border-border bg-card p-6 shadow-sm transition-colors hover:border-primary/40">
                <div className="flex h-9 w-9 items-center justify-center rounded bg-primary/10 text-primary">
                  <FileCheck2 className="h-4 w-4" />
                </div>
                <h3 className="mt-4 text-sm font-semibold text-foreground">
                  Verifiable Claim Grounding
                </h3>
                <p className="mt-2 flex-1 text-xs sm:text-sm text-muted-foreground leading-relaxed">
                  Every generated assertion is inspected against extracted source
                  chunks. Grounding scores and evidence excerpts establish direct
                  traceability back to the uploaded material.
                </p>
                <div className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                  Transparent attribution and conflict detection.
                </div>
              </div>

              {/* Capability 3 */}
              <div className="flex flex-col rounded-lg border border-border bg-card p-6 shadow-sm transition-colors hover:border-primary/40">
                <div className="flex h-9 w-9 items-center justify-center rounded bg-primary/10 text-primary">
                  <ShieldCheck className="h-4 w-4" />
                </div>
                <h3 className="mt-4 text-sm font-semibold text-foreground">
                  In-Process File Security &amp; PII Validation
                </h3>
                <p className="mt-2 flex-1 text-xs sm:text-sm text-muted-foreground leading-relaxed">
                  Rigorous input sanitization verifies MIME signatures, file
                  extensions, and structural integrity. Automated regex-based
                  PII detection tags sensitive identifiers before processing.
                </p>
                <div className="mt-4 border-t border-border/60 pt-3 text-xs text-muted-foreground">
                  Truthful operational states with no fabricated claims.
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Workflow overview */}
        <section className="border-t border-border py-16 sm:py-20">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-3xl rounded-xl border border-border bg-card p-6 sm:p-10 shadow-sm">
              <h2 className="text-lg sm:text-xl font-semibold text-foreground">
                Institutional Workflow
              </h2>
              <div className="mt-6 space-y-5">
                <div className="flex items-start gap-3.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-primary/10 text-xs font-semibold text-primary">
                    1
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Upload Authoritative Material
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Ingest PDF, DOCX, or plain text documents with in-process
                      structure validation and integrity verification.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-primary/10 text-xs font-semibold text-primary">
                    2
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Select Target Formats &amp; Strategy
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Specify the intended audience, communication tone, detail level,
                      and the desired outputs in a single configuration.
                    </p>
                  </div>
                </div>

                <div className="flex items-start gap-3.5">
                  <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded bg-primary/10 text-xs font-semibold text-primary">
                    3
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">
                      Review Verified Artifacts
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Inspect generated content side-by-side with grounding scores,
                      claim verification signals, and source evidence.
                    </p>
                  </div>
                </div>
              </div>

              <div className="mt-6 pt-5 border-t border-border/60 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  Ready to start transforming source documents?
                </span>
                <Link
                  href="/register"
                  className="inline-flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline"
                >
                  Create analyst account
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface-container-lowest py-8 text-center text-xs text-muted-foreground">
        <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <LogoMark size={20} />
            <span className="font-medium text-foreground">KaryaSetu AI</span>
            <span>— Policy-Aware Information Transformation System</span>
          </div>
          <div>
            <span>Operating under strictly bounded, verifiable AI pipelines.</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
