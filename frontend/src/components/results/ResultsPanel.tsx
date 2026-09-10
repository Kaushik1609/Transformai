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

import type { OutputResponse } from "@/lib/api";
import {
  outputTypeLabel,
  outputStatusVariant,
  outputFailureDetails,
} from "@/lib/outputTypes";
import { StatusBadge } from "@/components/common";
import { DownloadButton, CopyButton, ExportButton } from "@/components/export";
import { artifactOptions } from "@/components/export/DownloadButton";
import { VerificationPanel, FactVerificationPanel, ArtifactIntegrity } from "@/components/verification";

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

  return (
    <article className="rounded-lg border border-border">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-foreground">
            {outputTypeLabel(output.output_type)}
          </h3>
          <ArtifactIntegrity output={output} compact />
        </div>
        <StatusBadge variant={outputStatusVariant(output.status)}>
          {output.status}
        </StatusBadge>
      </header>

      <div className="space-y-3 px-4 py-3">
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
