/**
 * TransformIQ — Source content intelligence.
 *
 * Read-only display of a ready source's canonical analysis plus an "Analyze"
 * action that enqueues the backend analysis job. Kept lightweight — the
 * transformation workflow itself consumes canonical content server-side.
 */
"use client";

import { useEffect, useState } from "react";
import {
  type CanonicalContentResponse,
  type SourceResponse,
  contentIntelligenceApi,
  ApiError,
} from "@/lib/api";
import { LoadingSpinner, StatusBadge } from "@/components/common";

interface SourceAnalysisProps {
  source: SourceResponse;
}

export function SourceAnalysis({ source }: SourceAnalysisProps) {
  const [analysis, setAnalysis] = useState<CanonicalContentResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setAnalysis(null);
    contentIntelligenceApi
      .get(source.id)
      .then((res) => {
        if (!cancelled) setAnalysis(res.data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          setError(null); // not analyzed yet — expected
        } else {
          setError(
            err instanceof ApiError
              ? err.detail
              : "Failed to load source analysis.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [source.id]);

  const handleAnalyze = async () => {
    if (analyzing || source.status !== "ready") return;
    setAnalyzing(true);
    setError(null);
    try {
      const res = await contentIntelligenceApi.analyze(source.id);
      setAnalysis(res.data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to analyze.");
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" label="Loading analysis…" />
        Loading content intelligence…
      </div>
    );
  }

  if (error) {
    return (
      <p role="alert" className="text-xs font-medium text-destructive">
        {error}
      </p>
    );
  }

  if (!analysis) {
    return (
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          Content intelligence has not been created for this source.
        </p>
        {source.status === "ready" && (
          <button
            type="button"
            onClick={() => void handleAnalyze()}
            disabled={analyzing}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
          >
            {analyzing && <LoadingSpinner size="sm" label="Analyzing…" />}
            Analyze
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-foreground">
          Content intelligence
        </p>
        <StatusBadge variant={analysis.status === "completed" ? "success" : "info"}>
          {analysis.status}
        </StatusBadge>
      </div>
      {analysis.title && (
        <p className="mt-1.5 text-xs font-medium text-foreground">
          {analysis.title}
        </p>
      )}
      {analysis.summary && (
        <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-muted-foreground">
          {analysis.summary}
        </p>
      )}
    </div>
  );
}