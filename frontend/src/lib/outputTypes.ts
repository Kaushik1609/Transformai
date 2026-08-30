/**
 * TransformIQ — Output type registry and status helpers.
 *
 * The output type list is authoritative from the backend API contract
 * (summary | linkedin | x | advisory | infographic | presentation | video).
 * This module only provides presentational labels and status → badge mappings.
 */

import type { BadgeVariant } from "@/components/common";

export type OutputTypeId =
  | "summary"
  | "linkedin"
  | "x"
  | "advisory"
  | "infographic"
  | "presentation"
  | "video";

export interface OutputTypeInfo {
  id: OutputTypeId;
  label: string;
  description: string;
}

const OUTPUT_TYPE_LABELS: Record<OutputTypeId, string> = {
  summary: "Executive Summary",
  linkedin: "LinkedIn Post",
  x: "X Post",
  advisory: "Advisory Note",
  infographic: "Infographic",
  presentation: "Presentation",
  video: "Video",
};

export const OUTPUT_TYPES: OutputTypeInfo[] = [
  {
    id: "summary",
    label: OUTPUT_TYPE_LABELS.summary,
    description: "Concise, decision-ready overview of the source.",
  },
  {
    id: "linkedin",
    label: OUTPUT_TYPE_LABELS.linkedin,
    description: "Professional narrative for a LinkedIn audience.",
  },
  {
    id: "x",
    label: OUTPUT_TYPE_LABELS.x,
    description: "Short-form post for the X platform.",
  },
  {
    id: "advisory",
    label: OUTPUT_TYPE_LABELS.advisory,
    description: "Structured expert recommendation note.",
  },
  {
    id: "infographic",
    label: OUTPUT_TYPE_LABELS.infographic,
    description: "Visual one-page infographic (PNG + PDF companion).",
  },
  {
    id: "presentation",
    label: OUTPUT_TYPE_LABELS.presentation,
    description: "Slide deck exported as PPTX.",
  },
  {
    id: "video",
    label: OUTPUT_TYPE_LABELS.video,
    description: "Video package (PDF storyboard + SRT subtitles).",
  },
];

export function outputTypeLabel(outputType: string): string {
  const id = outputType as OutputTypeId;
  return id in OUTPUT_TYPE_LABELS ? OUTPUT_TYPE_LABELS[id] : outputType;
}

// ---------------------------------------------------------------------------
// Status → badge variant helpers (presentational only)
// ---------------------------------------------------------------------------

export function jobStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "queued":
      return "info";
    case "running":
      return "info";
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "cancelled":
      return "muted";
    default:
      return "default";
  }
}

export function outputStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "generating":
      return "info";
    case "completed":
      return "success";
    case "failed":
      return "error";
    default:
      return "default";
  }
}

export function sourceStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "ready":
      return "success";
    case "processing":
    case "uploaded":
      return "info";
    case "failed":
      return "error";
    default:
      return "default";
  }
}

export function verificationStatusVariant(status: string): BadgeVariant {
  switch (status) {
    case "success":
      return "success";
    case "warning":
      return "warning";
    case "failed":
      return "error";
    default:
      return "default";
  }
}

// ---------------------------------------------------------------------------
// Status predicates
// ---------------------------------------------------------------------------

export const TERMINAL_JOB_STATUSES = ["completed", "failed", "cancelled"];

export function isTerminalJobStatus(status: string): boolean {
  return TERMINAL_JOB_STATUSES.includes(status);
}

export function isTerminalOutputStatus(status: string): boolean {
  return status === "completed" || status === "failed";
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export function formatFileSize(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined || bytes < 0) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  const value = bytes / Math.pow(1024, index);
  const formatted = value.toFixed(value >= 10 || index === 0 ? 0 : 1);
  return `${formatted.replace(/\.0$/, "")} ${units[index]}`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString();
}