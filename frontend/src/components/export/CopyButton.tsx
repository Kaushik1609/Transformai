/**
 * TransformIQ — Copy-to-clipboard button (Phase 10).
 *
 * Copies the provided text using `copyText` (Clipboard API with a legacy
 * `execCommand` fallback) and shows a short-lived "Copied" confirmation.
 * Announces the result for assistive technology.
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/utils";
import { LoadingSpinner } from "@/components/common";

interface CopyButtonProps {
  /** The text to copy when clicked. */
  text: string;
  /** Optional label (defaults to "Copy"). */
  label?: string;
  /** Number of ms to show "Copied" confirmation (default 2000). */
  confirmMs?: number;
  /** Additional Tailwind classes. */
  className?: string;
}

export function CopyButton({
  text,
  label = "Copy",
  confirmMs = 2000,
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const handleCopy = async () => {
    if (busy || !text) return;
    setBusy(true);
    setError(null);
    const ok = await copyText(text);
    setBusy(false);
    if (ok) {
      setCopied(true);
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => setCopied(false), confirmMs);
    } else {
      setError("Copy failed. Select the text and copy manually.");
    }
  };

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      disabled={busy}
      className={
        className ??
        "inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
      }
      aria-label={copied ? "Copied to clipboard" : "Copy to clipboard"}
    >
      {busy ? (
        <LoadingSpinner size="sm" label="Copying…" />
      ) : copied ? (
        <svg
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          className="h-3.5 w-3.5 text-green-600"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="m4.5 12.75 6 6 9-13.5"
          />
        </svg>
      ) : (
        <svg
          aria-hidden="true"
          xmlns="http://www.w3.org/2000/svg"
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75"
          />
        </svg>
      )}
      {error ? (
        <span role="alert" className="text-destructive">
          {label}
        </span>
      ) : (
        <span>{copied ? "Copied!" : label}</span>
      )}
      <span className="sr-only" aria-live="polite">
        {copied ? "Copied to clipboard" : error ? error : ""}
      </span>
    </button>
  );
}