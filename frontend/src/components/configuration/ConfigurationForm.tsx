/**
 * TransformIQ — Generation configuration form.
 *
 * Collects audience, tone, language, detail level and communication objective
 * (plus optional content style / custom instructions) and creates a backend
 * configuration record for the project.
 */
"use client";

import { useState } from "react";
import {
  ConfigurationResponse,
  configurationsApi,
  ApiError,
} from "@/lib/api";
import { LoadingSpinner } from "@/components/common";

interface ConfigurationFormProps {
  projectId: string;
  onConfigCreated: (config: ConfigurationResponse) => void;
  disabled?: boolean;
}

interface FormState {
  target_audience: string;
  tone: string;
  language: string;
  detail_level: string;
  communication_objective: string;
  content_style: string;
  custom_instructions: string;
}

const EMPTY_FORM: FormState = {
  target_audience: "",
  tone: "",
  language: "English",
  detail_level: "standard",
  communication_objective: "",
  content_style: "",
  custom_instructions: "",
};

const DETAIL_LEVELS = ["concise", "standard", "detailed"];

export function ConfigurationForm({
  projectId,
  onConfigCreated,
  disabled = false,
}: ConfigurationFormProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const setField = (key: keyof FormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = async () => {
    if (submitting || disabled || !form.language.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const res = await configurationsApi.create(projectId, {
        target_audience: form.target_audience.trim() || null,
        tone: form.tone.trim() || null,
        language: form.language.trim(),
        detail_level: form.detail_level || null,
        communication_objective: form.communication_objective.trim() || null,
        content_style: form.content_style.trim() || null,
        custom_instructions: form.custom_instructions.trim() || null,
      });
      onConfigCreated(res.data);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.detail : "Failed to save configuration.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (disabled) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <LoadingSpinner size="sm" label="Loading…" />
        Loading configuration…
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <LabeledField label="Target audience" htmlFor="cf-audience">
          <input
            id="cf-audience"
            value={form.target_audience}
            onChange={(e) => setField("target_audience", e.target.value)}
            placeholder="e.g. technology executives"
            className="input-base"
          />
        </LabeledField>

        <LabeledField label="Tone" htmlFor="cf-tone">
          <input
            id="cf-tone"
            value={form.tone}
            onChange={(e) => setField("tone", e.target.value)}
            placeholder="e.g. professional, casual"
            className="input-base"
          />
        </LabeledField>

        <LabeledField label="Output language" htmlFor="cf-language">
          <input
            id="cf-language"
            value={form.language}
            onChange={(e) => setField("language", e.target.value)}
            placeholder="e.g. English, Hindi"
            className="input-base"
          />
        </LabeledField>

        <LabeledField label="Detail level" htmlFor="cf-detail">
          <select
            id="cf-detail"
            value={form.detail_level}
            onChange={(e) => setField("detail_level", e.target.value)}
            className="input-base"
          >
            {DETAIL_LEVELS.map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </LabeledField>

        <LabeledField
          label="Communication objective"
          htmlFor="cf-objective"
          className="sm:col-span-2"
        >
          <input
            id="cf-objective"
            value={form.communication_objective}
            onChange={(e) =>
              setField("communication_objective", e.target.value)
            }
            placeholder="e.g. inform, persuade, decision support"
            className="input-base"
          />
        </LabeledField>

        <LabeledField
          label="Content style (optional)"
          htmlFor="cf-style"
          className="sm:col-span-2"
        >
          <input
            id="cf-style"
            value={form.content_style}
            onChange={(e) => setField("content_style", e.target.value)}
            placeholder="e.g. narrative, bullet-points"
            className="input-base"
          />
        </LabeledField>

        <LabeledField
          label="Custom instructions (optional)"
          htmlFor="cf-instructions"
          className="sm:col-span-2"
        >
          <textarea
            id="cf-instructions"
            value={form.custom_instructions}
            onChange={(e) => setField("custom_instructions", e.target.value)}
            placeholder="Free-form guidance for the AI…"
            rows={3}
            className="input-base resize-y"
          />
        </LabeledField>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => void handleSubmit()}
          disabled={submitting || !form.language.trim()}
          className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting && <LoadingSpinner size="sm" label="Saving…" />}
          Save configuration
        </button>
        {error && (
          <p role="alert" className="text-xs font-medium text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

interface LabeledFieldProps {
  label: string;
  htmlFor: string;
  className?: string;
  children: React.ReactNode;
}

function LabeledField({ label, htmlFor, className, children }: LabeledFieldProps) {
  return (
    <div className={className ? `space-y-1 ${className}` : "space-y-1"}>
      <label
        htmlFor={htmlFor}
        className="text-xs font-medium text-muted-foreground"
      >
        {label}
      </label>
      {children}
    </div>
  );
}