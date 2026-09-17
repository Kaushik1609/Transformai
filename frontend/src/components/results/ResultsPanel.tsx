/**
 * TransformIQ — Results panel.
 *
 * Renders the outputs of a transformation job: one card per output with its
 * type label, status, generated text content, downloadable artifacts and
 * verification state. Failed outputs surface safe failure details and are
 * never hidden; binary outputs without an available artifact show a clear
 * "Not available" state instead of silently dropping the download.
 */
"use client";

import { useState } from "react";
import { type OutputResponse, outputsApi } from "@/lib/api";
import {
  outputTypeLabel,
  outputStatusVariant,
  outputFailureDetails,
} from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import { DownloadButton, CopyButton, ExportButton } from "@/components/export";
import { artifactOptions } from "@/components/export/DownloadButton";
import { VerificationPanel, FactVerificationPanel, ArtifactIntegrity, ProvenancePanel } from "@/components/verification";

interface ResultsPanelProps {
  outputs: OutputResponse[];
  loading?: boolean;
}

const BINARY_OUTPUT_TYPES = new Set([
  "infographic",
  "presentation",
  "video",
]);

export function ResultsPanel({ outputs, loading = false }: ResultsPanelProps) {
  if (loading) {
    return (
      <p className="text-xs text-muted-foreground">Loading outputs…</p>
    );
  }

  if (outputs.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        No outputs generated yet.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      {outputs.map((output) => (
        <OutputCard key={output.id} output={output} />
      ))}
    </div>
  );
}

function OutputCard({ output }: { output: OutputResponse }) {
  const failed = output.status === "failed";
  const generating = output.status === "generating";
  const isBinary = BINARY_OUTPUT_TYPES.has(output.output_type);
  const hasArtifact = artifactOptions(output).length > 0;
  const failure = outputFailureDetails(output);
  const dissemination = output.output_metadata?.dissemination as
    | {
        primary_decision?: "ALLOW" | "BLOCK" | "REVIEW";
        primary_reason?: string;
      }
    | undefined;

  let dissemBadge: { label: string; className: string; reason?: string } | null = null;
  if (dissemination?.primary_decision === "ALLOW") {
    dissemBadge = {
      label: "Allowed",
      className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
      reason: dissemination.primary_reason,
    };
  } else if (dissemination?.primary_decision === "REVIEW") {
    dissemBadge = {
      label: "Requires review",
      className: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
      reason: dissemination.primary_reason,
    };
  } else if (dissemination?.primary_decision === "BLOCK") {
    dissemBadge = {
      label: "Blocked by policy",
      className: "bg-destructive/10 text-destructive",
      reason: dissemination.primary_reason,
    };
  }

  const [acting, setActing] = useState(false);
  const [localStatus, setLocalStatus] = useState<string | null>(null);

  const approvalMeta = output.output_metadata?.approval as
    | {
        destinations?: Record<
          string,
          {
            approval_status?: string;
            approval_id?: string;
            rejection_reason?: string;
          }
        >;
      }
    | undefined;

  const downloadApproval = approvalMeta?.destinations?.["DOWNLOAD"];
  const effectiveStatus = localStatus || downloadApproval?.approval_status;

  let approvalBadge: { label: string; className: string } | null = null;
  if (effectiveStatus === "PENDING_APPROVAL") {
    approvalBadge = {
      label: "Pending Approval",
      className: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20",
    };
  } else if (effectiveStatus === "APPROVED") {
    approvalBadge = {
      label: "Approved",
      className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20",
    };
  } else if (effectiveStatus === "REJECTED") {
    approvalBadge = {
      label: "Rejected",
      className: "bg-destructive/10 text-destructive border border-destructive/20",
    };
  }

  // Classification badge
  const classification = (
    output.output_metadata?.classification ||
    (output.output_metadata?.provenance as any)?.source?.classification ||
    (output.output_metadata?.provenance as any)?.policy_routing?.classification
  ) as string | undefined;

  let classificationBadge: { label: string; className: string } | null = null;
  if (classification) {
    const uc = classification.toUpperCase();
    if (uc === "RESTRICTED") {
      classificationBadge = {
        label: uc,
        className: "bg-red-500/10 text-red-600 dark:text-red-400 border border-red-500/20",
      };
    } else if (uc === "CONFIDENTIAL") {
      classificationBadge = {
        label: uc,
        className: "bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20",
      };
    } else if (uc === "INTERNAL") {
      classificationBadge = {
        label: uc,
        className: "bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20",
      };
    } else {
      classificationBadge = {
        label: uc,
        className: "bg-muted/70 text-muted-foreground border border-border/50",
      };
    }
  }

  // Execution route badge (Local / Offline / Cloud)
  const routing = (
    output.output_metadata?.policy_routing ||
    (output.output_metadata?.provenance as any)?.policy_routing
  ) as {
    processing_route?: string;
    provider_category?: string;
    provider_id?: string;
    model_id?: string;
  } | undefined;

  const routeVal = (routing?.processing_route || routing?.provider_category)?.toUpperCase();
  let routeBadge: { label: string; className: string; tooltip?: string } | null = null;
  if (routeVal === "LOCAL" || routeVal === "OFFLINE" || routeVal === "AIR_GAPPED") {
    routeBadge = {
      label: routeVal === "AIR_GAPPED" ? "Air-Gapped" : routeVal === "OFFLINE" ? "Offline" : "Local",
      className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20",
      tooltip: routing?.model_id ? `${routing.provider_id || "local"}: ${routing.model_id}` : "Local/offline execution",
    };
  } else if (routeVal === "CLOUD") {
    routeBadge = {
      label: "Cloud",
      className: "bg-sky-500/10 text-sky-600 dark:text-sky-400 border border-sky-500/20",
      tooltip: routing?.model_id ? `${routing.provider_id || "cloud"}: ${routing.model_id}` : "Cloud execution",
    };
  }

  // Digital signature badge
  const digitalSig = output.output_metadata?.digital_signature as
    | { status?: string; algorithm?: string; key_id?: string }
    | undefined;

  let sigBadge: { label: string; className: string; tooltip?: string } | null = null;
  if (digitalSig?.status === "VALID") {
    sigBadge = {
      label: `Signed · ${digitalSig.algorithm || "Ed25519"}`,
      className: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20",
      tooltip: `Key ID: ${digitalSig.key_id || "authoritative"}`,
    };
  } else if (digitalSig?.status === "INVALID") {
    sigBadge = {
      label: "Signature Invalid",
      className: "bg-destructive/10 text-destructive border border-destructive/20",
      tooltip: "Signature verification failed",
    };
  }

  const handleApprove = async () => {
    try {
      setActing(true);
      await outputsApi.submitApproval(output.id, {
        destination: "DOWNLOAD",
        action: "approve",
        comments: "Approved via workspace interface",
      });
      setLocalStatus("APPROVED");
    } catch {
      // Keep state fail-closed on error
    } finally {
      setActing(false);
    }
  };

  const handleReject = async () => {
    const reason = window.prompt("Enter reason for rejecting this output artifact:");
    if (!reason || !reason.trim()) return;
    try {
      setActing(true);
      await outputsApi.submitApproval(output.id, {
        destination: "DOWNLOAD",
        action: "reject",
        rejection_reason: reason.trim(),
      });
      setLocalStatus("REJECTED");
    } catch {
      // Keep state fail-closed on error
    } finally {
      setActing(false);
    }
  };

  return (
    <article className="rounded-lg border border-border">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {outputTypeLabel(output.output_type)}
          </h3>
          {classificationBadge && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${classificationBadge.className}`}
              data-testid={`classification-badge-${output.id}`}
            >
              {classificationBadge.label}
            </span>
          )}
          {routeBadge && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${routeBadge.className}`}
              title={routeBadge.tooltip}
              data-testid={`route-badge-${output.id}`}
            >
              {routeBadge.label}
            </span>
          )}
          <ArtifactIntegrity output={output} compact />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {sigBadge && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${sigBadge.className}`}
              title={sigBadge.tooltip}
              data-testid={`signature-badge-${output.id}`}
            >
              {sigBadge.label}
            </span>
          )}
          {approvalBadge && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${approvalBadge.className}`}
              data-testid={`approval-badge-${output.id}`}
            >
              {approvalBadge.label}
            </span>
          )}
          {dissemBadge && (
            <span
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium ${dissemBadge.className}`}
              title={dissemBadge.reason || dissemBadge.label}
              data-testid={`dissemination-badge-${output.id}`}
            >
              {dissemBadge.label}
            </span>
          )}
          <StatusBadge variant={outputStatusVariant(output.status)}>
            {output.status}
          </StatusBadge>
        </div>
      </header>

      <div className="space-y-3 px-4 py-3">
        {effectiveStatus === "PENDING_APPROVAL" && (
          <p className="text-xs text-amber-600 dark:text-amber-400 font-medium" role="alert">
            Controlled release: Human approval required before downloading or exporting this artifact.
          </p>
        )}
        {effectiveStatus === "REJECTED" && (
          <p className="text-xs text-destructive font-medium" role="alert">
            Release blocked: Artifact was rejected by reviewer{downloadApproval?.rejection_reason ? `: ${downloadApproval.rejection_reason}` : "."}
          </p>
        )}
        {dissemBadge && dissemBadge.label === "Blocked by policy" && (
          <p className="text-xs text-destructive font-medium" role="alert">
            Dissemination blocked by policy: {dissemBadge.reason}
          </p>
        )}
        {dissemBadge && dissemBadge.label === "Requires review" && (
          <p className="text-xs text-amber-600 dark:text-amber-400 font-medium">
            Dissemination requires review: {dissemBadge.reason}
          </p>
        )}
        {generating && (
          <p className="text-xs text-muted-foreground">
            This output is still being generated…
          </p>
        )}

        {failed && (
          <FailureDetails output={output} failure={failure} />
        )}

        {!failed && (
          <OutputContent output={output} />
        )}

        {!failed && effectiveStatus === "PENDING_APPROVAL" && (
          <div className="flex items-center gap-2 pt-1 border-t border-border/40">
            <button
              type="button"
              disabled={acting}
              onClick={() => void handleApprove()}
              className="inline-flex items-center rounded-md bg-emerald-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-emerald-700 disabled:opacity-50"
              data-testid={`approve-btn-${output.id}`}
            >
              {acting ? "Approving…" : "Approve Release"}
            </button>
            <button
              type="button"
              disabled={acting}
              onClick={() => void handleReject()}
              className="inline-flex items-center rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/20 disabled:opacity-50"
              data-testid={`reject-btn-${output.id}`}
            >
              Reject
            </button>
          </div>
        )}

        {!failed && (
          <div className="flex flex-wrap items-center gap-2">
            {output.text_content && (
              <CopyButton
                text={output.text_content}
                label={`Copy ${outputTypeLabel(output.output_type)}`}
              />
            )}
            {(output.output_type === "summary" ||
              output.output_type === "advisory") && (
              <>
                <ExportButton
                  outputId={output.id}
                  format="docx"
                  label={`Download ${outputTypeLabel(output.output_type)}`}
                />
                <ExportButton
                  outputId={output.id}
                  format="pdf"
                  label={`Download ${outputTypeLabel(output.output_type)}`}
                />
              </>
            )}
            <DownloadButton
              output={output}
              label={`Download ${outputTypeLabel(output.output_type)}`}
            />
          </div>
        )}

        {!failed && isBinary && output.status === "completed" && !hasArtifact && (
          <p className="text-xs font-medium text-muted-foreground">
            Not available — this output has no downloadable artifact.
          </p>
        )}

        {!failed && <VerificationPanel outputId={output.id} />}

        {output.status === "completed" && (
          <FactVerificationPanel outputId={output.id} />
        )}
        {!failed && output.status === "completed" && (
          <ProvenancePanel outputId={output.id} />
        )}
      </div>
    </article>
  );
}

export function FailureDetails({
  output,
  failure,
}: {
  output: OutputResponse;
  failure: ReturnType<typeof outputFailureDetails>;
}) {
  return (
    <div className="space-y-2" role="alert">
      <p className="text-xs font-medium text-destructive">
        This output failed to generate.
      </p>
      {failure?.message && (
        <p className="text-xs text-muted-foreground">{failure.message}</p>
      )}
      {failure && (
        <dl className="space-y-1 text-[11px] text-muted-foreground">
          {failure.errorType && (
            <Row label="Error type" value={failure.errorType} />
          )}
          {failure.attempts !== null && (
            <Row
              label="Attempts"
              value={
                failure.maxAttempts !== null
                  ? `${failure.attempts} of ${failure.maxAttempts}`
                  : String(failure.attempts)
              }
            />
          )}
          {failure.retryExhausted && (
            <Row label="Automatic retries" value="Exhausted" />
          )}
          {failure.usedFallback === true && (
            <Row label="Fallback provider" value="Used" />
          )}
          {failure.usedFallback === false && (
            <Row label="Fallback provider" value="Not used" />
          )}
          {failure.provider && <Row label="Provider" value={failure.provider} />}
        </dl>
      )}
    </div>
  );
}

export function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="shrink-0 uppercase tracking-wide">{label}</dt>
      <dd className="text-right">{value}</dd>
    </div>
  );
}

export function OutputContent({ output }: { output: OutputResponse }) {
  // Structured, type-specific previews (safe enumerable fields only).
  if (output.output_type === "x") {
    return <XThreadView output={output} />;
  }
  if (output.output_type === "presentation") {
    return <SlideView output={output} />;
  }
  if (output.output_type === "infographic") {
    return <InfographicView output={output} />;
  }
  if (output.output_type === "video") {
    return <VideoView output={output} />;
  }

  if (output.text_content) {
    return (
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 font-sans text-xs leading-relaxed text-foreground">
        {output.text_content}
      </pre>
    );
  }

  return (
    <p className="text-xs text-muted-foreground">
      Content prepared — no text preview available.
    </p>
  );
}

export function XThreadView({ output }: { output: OutputResponse }) {
  const thread = (output.structured_content as { thread?: unknown } | null)
    ?.thread;
  if (Array.isArray(thread) && thread.length > 0) {
    return (
      <ol className="space-y-2">
        {thread.map((post, i) =>
          typeof post === "string" ? (
            <li
              key={i}
              className="rounded-md border border-border bg-muted/30 p-2.5 text-xs leading-relaxed text-foreground"
            >
              <span className="mr-2 font-semibold text-primary">
                Post {i + 1}
              </span>
              {post}
            </li>
          ) : null,
        )}
      </ol>
    );
  }
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 font-sans text-xs leading-relaxed text-foreground">
      {output.text_content}
    </pre>
  );
}

interface SlideData {
  title?: unknown;
  key_message?: unknown;
}

export function SlideView({ output }: { output: OutputResponse }) {
  const raw = output.structured_content as {
    slides?: unknown;
    title?: unknown;
  } | null;
  const slides = Array.isArray(raw?.slides) ? (raw.slides as SlideData[]) : [];
  if (slides.length > 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          {slides.length} slide{slides.length !== 1 ? "s" : ""}
          {typeof raw?.title === "string" ? ` · ${raw.title}` : ""}
        </p>
        <ol className="space-y-2">
          {slides.map((slide, i) => (
            <li
              key={i}
              className="rounded-md border border-border bg-muted/30 p-2.5 text-xs leading-relaxed text-foreground"
            >
              <p className="font-semibold text-primary">
                Slide {i + 1}
                {typeof slide.title === "string" ? ` · ${slide.title}` : ""}
              </p>
              {typeof slide.key_message === "string" &&
                slide.key_message.length > 0 && (
                  <p className="mt-1">{slide.key_message}</p>
                )}
            </li>
          ))}
        </ol>
      </div>
    );
  }
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 font-sans text-xs leading-relaxed text-foreground">
      {output.text_content}
    </pre>
  );
}

interface SectionData {
  heading?: unknown;
  message?: unknown;
}

export function InfographicView({ output }: { output: OutputResponse }) {
  const raw = output.structured_content as {
    sections?: unknown;
    key_messages?: unknown;
  } | null;
  const sections = Array.isArray(raw?.sections)
    ? (raw.sections as SectionData[])
    : [];
  if (sections.length > 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          {sections.length} section{sections.length !== 1 ? "s" : ""}
        </p>
        <ol className="space-y-2">
          {sections.map((section, i) => (
            <li
              key={i}
              className="rounded-md border border-border bg-muted/30 p-2.5 text-xs leading-relaxed text-foreground"
            >
              {typeof section.heading === "string" &&
                section.heading.length > 0 && (
                  <p className="font-semibold text-primary">
                    {section.heading}
                  </p>
                )}
              {typeof section.message === "string" &&
                section.message.length > 0 && (
                  <p className="mt-0.5">{section.message}</p>
                )}
            </li>
          ))}
        </ol>
      </div>
    );
  }
  return (
    <p className="text-xs text-muted-foreground">
      Content prepared — no text preview available.
    </p>
  );
}

interface SceneData {
  title?: unknown;
  narration?: unknown;
}

export function VideoView({ output }: { output: OutputResponse }) {
  const raw = output.structured_content as {
    storyboard?: unknown;
    script?: unknown;
  } | null;
  const storyboard = Array.isArray(raw?.storyboard)
    ? (raw.storyboard as SceneData[])
    : [];
  if (storyboard.length > 0) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-muted-foreground">
          {storyboard.length} scene{storyboard.length !== 1 ? "s" : ""}
        </p>
        <ol className="space-y-2">
          {storyboard.map((scene, i) => (
            <li
              key={i}
              className="rounded-md border border-border bg-muted/30 p-2.5 text-xs leading-relaxed text-foreground"
            >
              <p className="font-semibold text-primary">
                Scene {i + 1}
                {typeof scene.title === "string" && scene.title.length > 0
                  ? ` · ${scene.title}`
                  : ""}
              </p>
              {typeof scene.narration === "string" &&
                scene.narration.length > 0 && (
                  <p className="mt-0.5">{scene.narration}</p>
                )}
            </li>
          ))}
        </ol>
        {typeof raw?.script === "string" && raw.script.length > 0 && (
          <details className="rounded-md border border-border bg-muted/30 px-2.5 py-2">
            <summary className="cursor-pointer text-xs font-semibold text-foreground">
              Full script
            </summary>
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-sans text-xs leading-relaxed text-foreground">
              {raw.script}
            </pre>
          </details>
        )}
      </div>
    );
  }
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-md bg-muted/30 p-3 font-sans text-xs leading-relaxed text-foreground">
      {output.text_content}
    </pre>
  );
}
