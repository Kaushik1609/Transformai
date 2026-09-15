/**
 * TransformIQ / KaryaSetu AI — Canonical Provenance Panel (Phase 2E).
 *
 * Renders the end-to-end lineage chain for an output:
 *   SOURCE -> EVIDENCE -> TRANSFORMATION -> POLICY & ROUTING -> GENERATOR -> VERIFICATION -> DISSEMINATION -> INTEGRITY
 *
 * Queries GET /api/v1/outputs/{output_id}/provenance.
 */
"use client";

import { useState } from "react";
import {
  type ProvenanceRecord,
  outputsApi,
  ApiError,
} from "@/lib/api";
import { GitCommit, ChevronDown, ChevronUp, FileText, CheckCircle2, XCircle, AlertCircle, Database, Shield, Lock } from "lucide-react";

interface ProvenancePanelProps {
  outputId: string;
}

export function ProvenancePanel({ outputId }: ProvenancePanelProps) {
  const [provenance, setProvenance] = useState<ProvenanceRecord | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadProvenance() {
    if (provenance) {
      setExpanded(!expanded);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await outputsApi.provenance(outputId);
      setProvenance(resp.data);
      setExpanded(true);
    } catch (err: unknown) {
      setError(
        err instanceof ApiError
          ? err.detail
          : "Provenance record could not be loaded.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2 pt-1 border-t border-border/60">
      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={() => void loadProvenance()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-muted/30 px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted/70 disabled:cursor-not-allowed disabled:opacity-60"
          data-testid={`provenance-toggle-${outputId}`}
        >
          <GitCommit className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
          {loading ? "Loading provenance…" : expanded ? "Hide Lineage & Provenance" : "View Lineage & Provenance"}
          {expanded ? (
            <ChevronUp className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
          )}
        </button>
        {provenance && (
          <span className="text-[11px] font-mono text-muted-foreground">
            {provenance.provenance_id}
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}

      {expanded && provenance && (
        <div
          className="rounded-lg border border-border/80 bg-card p-3 text-xs space-y-3"
          data-testid={`provenance-content-${outputId}`}
        >
          {/* Step 1: Source */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <FileText className="h-3.5 w-3.5 text-blue-500" />
              <span>1. Source Document</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground pl-5">
              <div>
                <span className="text-foreground">Filename: </span>
                {provenance.source.original_filename || "Prompt-only (no file)"}
              </div>
              <div>
                <span className="text-foreground">Classification: </span>
                <span className="font-semibold">{provenance.source.classification}</span>
              </div>
              <div>
                <span className="text-foreground">Source ID: </span>
                <span className="font-mono">{provenance.source.source_id ? provenance.source.source_id.slice(0, 8) + "…" : "n/a"}</span>
              </div>
              <div>
                <span className="text-foreground">Content Digest: </span>
                <span className="font-mono">{provenance.source.source_content_hash || "n/a"}</span>
              </div>
            </dl>
          </div>

          {/* Step 2: Evidence Grounding */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <Database className="h-3.5 w-3.5 text-indigo-500" />
              <span>2. Evidence Grounding (RAG)</span>
            </div>
            <div className="text-[11px] text-muted-foreground pl-5 space-y-1">
              <p>
                Method: <span className="font-mono">{provenance.evidence.retrieval_method}</span> ({provenance.evidence.chunks_count} chunks retrieved)
              </p>
              {provenance.evidence.citations.length > 0 && (
                <div className="space-y-1">
                  {provenance.evidence.citations.map((c, i) => (
                    <div key={i} className="rounded bg-muted/40 p-1.5 text-[11px]">
                      <div className="flex items-center justify-between text-foreground">
                        <span>Chunk #{c.chunk_index}</span>
                        {typeof c.relevance_score === "number" && (
                          <span className="font-mono text-[10px]">sim: {c.relevance_score.toFixed(3)}</span>
                        )}
                      </div>
                      <p className="italic line-clamp-2 text-muted-foreground mt-0.5">&ldquo;{c.excerpt}&rdquo;</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Step 3: Policy & AI Routing */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <Shield className="h-3.5 w-3.5 text-emerald-500" />
              <span>3. Policy & AI Routing</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground pl-5">
              <div>
                <span className="text-foreground">Processing Route: </span>
                <span className="font-medium text-foreground">{provenance.policy_routing.processing_route}</span>
              </div>
              <div>
                <span className="text-foreground">Provider / Model: </span>
                <span className="font-medium text-foreground">{provenance.policy_routing.provider_id} / {provenance.policy_routing.model_id}</span>
              </div>
              <div className="col-span-2">
                <span className="text-foreground">Category: </span>
                <span>{provenance.policy_routing.provider_category}</span>
              </div>
            </dl>
          </div>

          {/* Step 4: Generator & Verification */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <CheckCircle2 className="h-3.5 w-3.5 text-teal-500" />
              <span>4. Generator & Verification</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground pl-5">
              <div>
                <span className="text-foreground">Generator: </span>
                <span>{provenance.generator.generator_class}</span>
              </div>
              <div>
                <span className="text-foreground">Schema: </span>
                <span>{provenance.generator.schema_name || "n/a"}</span>
              </div>
              <div>
                <span className="text-foreground">Fact Verification: </span>
                <span className="font-medium">{provenance.verification.has_verification ? provenance.verification.overall_status : "Not run"}</span>
              </div>
              <div>
                <span className="text-foreground">Grounding Score: </span>
                <span>{provenance.verification.grounding_score !== null && provenance.verification.grounding_score !== undefined ? `${(provenance.verification.grounding_score * 100).toFixed(0)}%` : "n/a"}</span>
              </div>
            </dl>
          </div>

          {/* Step 5: Dissemination & Integrity */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 font-semibold text-foreground">
              <Lock className="h-3.5 w-3.5 text-amber-500" />
              <span>5. Dissemination & Integrity</span>
            </div>
            <dl className="grid grid-cols-2 gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground pl-5">
              <div>
                <span className="text-foreground">Dissemination: </span>
                <span className={provenance.dissemination.primary_allowed ? "text-emerald-600 font-medium" : "text-destructive font-medium"}>
                  {provenance.dissemination.primary_decision} ({provenance.dissemination.primary_destination})
                </span>
              </div>
              <div>
                <span className="text-foreground">Integrity Digest: </span>
                <span className="font-mono">{provenance.integrity.content_digest ? provenance.integrity.content_digest.slice(0, 12) + "…" : "n/a"}</span>
              </div>
              {provenance.extensions?.approval_id && (
                <div>
                  <span className="text-foreground">Approval ID: </span>
                  <span className="font-mono text-emerald-600 dark:text-emerald-400">{provenance.extensions.approval_id}</span>
                </div>
              )}
            </dl>
          </div>
        </div>
      )}
    </div>
  );
}
