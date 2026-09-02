/**
 * TransformIQ — Output type registry, icons, accent colors and selectable cards.
 *
 * The output type id list is authoritative from the backend API contract
 * (summary | linkedin | x | advisory | infographic | presentation | video).
 *
 * Each output type carries:
 *   - a presentational label
 *   - consumer-facing description
 *   - a unique accent color used subtly for icons / selected borders / badges
 *   - an icon (lucide-react)
 */
import { type LucideIcon, FileText, Linkedin, AlertTriangle, Presentation, X as XIcon, Image, Video } from "lucide-react";

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
  shortLabel: string;
  description: string;
  /** Tailwind text color class for the icon. */
  iconClass: string;
  /** Tailwind accent border / ring color. */
  accentClass: string;
  /** Tailwind subtle background tint. */
  tintClass: string;
  icon: LucideIcon;
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

const SHORT_LABELS: Record<OutputTypeId, string> = {
  summary: "Summary",
  linkedin: "LinkedIn",
  x: "X Thread",
  advisory: "Advisory",
  infographic: "Infographic",
  presentation: "Presentation",
  video: "Video",
};

export const OUTPUT_TYPES: OutputTypeInfo[] = [
  {
    id: "summary",
    label: OUTPUT_TYPE_LABELS.summary,
    shortLabel: SHORT_LABELS.summary,
    description: "Concise, decision-ready overview of your source.",
    iconClass: "text-output-summary",
    accentClass: "border-output-summary/60",
    tintClass: "bg-output-summary/10",
    icon: FileText,
  },
  {
    id: "linkedin",
    label: OUTPUT_TYPE_LABELS.linkedin,
    shortLabel: SHORT_LABELS.linkedin,
    description: "Professional narrative for a LinkedIn audience.",
    iconClass: "text-output-linkedin",
    accentClass: "border-output-linkedin/60",
    tintClass: "bg-output-linkedin/10",
    icon: Linkedin,
  },
  {
    id: "advisory",
    label: OUTPUT_TYPE_LABELS.advisory,
    shortLabel: SHORT_LABELS.advisory,
    description: "Structured expert recommendation note.",
    iconClass: "text-output-advisory",
    accentClass: "border-output-advisory/60",
    tintClass: "bg-output-advisory/10",
    icon: AlertTriangle,
  },
  {
    id: "presentation",
    label: OUTPUT_TYPE_LABELS.presentation,
    shortLabel: SHORT_LABELS.presentation,
    description: "Slide deck, exported as PPTX.",
    iconClass: "text-output-presentation",
    accentClass: "border-output-presentation/60",
    tintClass: "bg-output-presentation/10",
    icon: Presentation,
  },
  {
    id: "x",
    label: OUTPUT_TYPE_LABELS.x,
    shortLabel: SHORT_LABELS.x,
    description: "Short-form post for the X platform.",
    iconClass: "text-output-x",
    accentClass: "border-output-x/60",
    tintClass: "bg-output-x/5",
    icon: XIcon,
  },
  {
    id: "infographic",
    label: OUTPUT_TYPE_LABELS.infographic,
    shortLabel: SHORT_LABELS.infographic,
    description: "Visual one-page infographic (PNG + PDF companion).",
    iconClass: "text-output-infographic",
    accentClass: "border-output-infographic/60",
    tintClass: "bg-output-infographic/10",
    icon: Image,
  },
  {
    id: "video",
    label: OUTPUT_TYPE_LABELS.video,
    shortLabel: SHORT_LABELS.video,
    description: "Video package (PDF storyboard + SRT subtitles).",
    iconClass: "text-output-video",
    accentClass: "border-output-video/60",
    tintClass: "bg-output-video/10",
    icon: Video,
  },
];

export function outputTypeLabel(outputType: string): string {
  const id = outputType as OutputTypeId;
  return id in OUTPUT_TYPE_LABELS ? OUTPUT_TYPE_LABELS[id] : outputType;
}

export function outputTypeShortLabel(outputType: string): string {
  const id = outputType as OutputTypeId;
  return id in SHORT_LABELS ? SHORT_LABELS[id] : outputType;
}

export function outputTypeInfo(id: OutputTypeId): OutputTypeInfo {
  return OUTPUT_TYPES.find((o) => o.id === id) ?? OUTPUT_TYPES[0];
}

// ---------------------------------------------------------------------------
// Status → badge variant helpers (presentational only)
// ---------------------------------------------------------------------------

import type { BadgeVariant } from "@/components/common";

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
    case "passed":
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

/** Humanised relative time, e.g. "2 hours ago". """
 */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  const units: [number, string][] = [
    [60, "second"],
    [60, "minute"],
    [24, "hour"],
    [7, "day"],
    [4.348, "week"],
    [12, "month"],
  ];
  let value = seconds;
  let label = "second";
  for (const [div, name] of units) {
    if (value < div) {
      label = name;
      break;
    }
    value = Math.floor(value / div);
    label = name;
  }
  if (value === 0) return "just now";
  return `${value} ${label}${value !== 1 ? "s" : ""} ago`;
}
