/**
 * TransformIQ — Source upload.
 *
 * Lets a user add source material to a project either as a pasted text block
 * or as a file (TXT / PDF / DOCX per the backend contract). Handles the
 * "uploading" state and surfaces backend validation errors inline.
 */
"use client";

import { useRef, useState } from "react";
import {
  type SourceResponse,
  type InformationClassification,
  sourcesApi,
  ApiError,
} from "@/lib/api";
import { LoadingSpinner, StatusBadge } from "@/components/common";
import { cn } from "@/lib/utils";

type InputMode = "text" | "file";

interface SourceUploadProps {
  projectId: string;
  onSourceAdded: (source: SourceResponse) => void;
  disabled?: boolean;
}

const ACCEPTED = [".txt", ".pdf", ".docx"];

export function SourceUpload({
  projectId,
  onSourceAdded,
  disabled = false,
}: SourceUploadProps) {
  const [mode, setMode] = useState<InputMode>("text");
  const [classification, setClassification] =
    useState<InformationClassification>("INTERNAL");
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmitText = async () => {
    if (!text.trim() || submitting || disabled) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await sourcesApi.ingestText(
        projectId,
        text,
        "en",
        classification,
      );
      setText("");
      onSourceAdded(res.data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to add source.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitFile = async () => {
    if (!file || submitting || disabled) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await sourcesApi.ingestFile(projectId, file, classification);
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      onSourceAdded(res.data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to upload file.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* Information classification selector */}
      <div className="space-y-1">
        <label
          htmlFor="classification-select"
          className="block text-xs font-medium text-foreground"
        >
          Information classification
        </label>
        <select
          id="classification-select"
          aria-label="Information classification"
          value={classification}
          onChange={(e) =>
            setClassification(e.target.value as InformationClassification)
          }
          disabled={disabled || submitting}
          className="w-full rounded-md border border-input bg-background px-3 py-1.5 text-xs text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="PUBLIC">PUBLIC — Cloud processing allowed</option>
          <option value="INTERNAL">
            INTERNAL — Controlled internal processing (Default)
          </option>
          <option value="CONFIDENTIAL">
            CONFIDENTIAL — Private / local processing required
          </option>
          <option value="RESTRICTED">
            RESTRICTED — Private / local required (Cloud denied)
          </option>
        </select>
        <p className="text-[11px] text-muted-foreground">
          KaryaSetu internal policy label. Does not represent official government
          classification.
        </p>
      </div>

      {/* Mode tabs */}
      <div className="inline-flex rounded-md border border-border bg-muted/40 p-0.5">
        {(["text", "file"] as InputMode[]).map((m) => (
          <button
            key={m}
            type="button"
            disabled={disabled || submitting}
            onClick={() => setMode(m)}
            className={cn(
              "rounded px-3 py-1 text-xs font-medium transition-colors",
              mode === m
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {m === "text" ? "Text" : "File"}
          </button>
        ))}
      </div>

      {mode === "text" ? (
        <div className="space-y-2">
          <textarea
            aria-label="Source text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={disabled || submitting}
            placeholder="Paste the source content here…"
            rows={6}
            className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSubmitText()}
              disabled={disabled || submitting || !text.trim()}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <LoadingSpinner size="sm" label="Uploading…" />
                  Uploading…
                </>
              ) : (
                "Add text source"
              )}
            </button>
            {text.trim().length > 0 && !submitting && (
              <StatusBadge variant="info">
                {text.trim().length.toLocaleString()} characters
              </StatusBadge>
            )}
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed border-border bg-muted/30 px-4 py-6 text-center transition-colors hover:bg-muted/50">
            {file ? (
              <>
                <p className="text-sm font-medium text-foreground">
                  {file.name}
                </p>
                <p className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </>
            ) : (
              <>
                <p className="text-sm font-medium text-foreground">
                  Choose a file to upload
                </p>
                <p className="text-xs text-muted-foreground">
                  Supported: TXT, PDF, DOCX
                </p>
              </>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPTED.join(",")}
              aria-label="Source file input"
              disabled={disabled || submitting}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="sr-only"
            />
          </label>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSubmitFile()}
              disabled={disabled || submitting || !file}
              className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? (
                <>
                  <LoadingSpinner size="sm" label="Uploading…" />
                  Uploading…
                </>
              ) : (
                "Upload file"
              )}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="text-xs font-medium text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}