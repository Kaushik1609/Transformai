/**
 * TransformIQ — Progress bar component.
 *
 * Determinate when a 0–100 value is provided; indeterminate (subtle animated
 * sweep) when progress is unknown — e.g. while a job is running but the
 * backend still reports 0 progress.
 */
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  /** 0–100 determinate value, or null/undefined for indeterminate. */
  value?: number | null;
  /** Accessible label. */
  label?: string;
  className?: string;
}

export function ProgressBar({
  value,
  label = "Progress",
  className,
}: ProgressBarProps) {
  const determinate = value !== null && value !== undefined;
  const pct = determinate ? Math.max(0, Math.min(100, value)) : 0;

  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={determinate ? pct : undefined}
      className={cn(
        "relative h-2 w-full overflow-hidden rounded-full bg-border/60",
        className,
      )}
    >
      {determinate ? (
        <div
          className="h-full rounded-full bg-primary transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      ) : (
        <div className="h-full w-1/3 animate-pulse rounded-full bg-primary" />
      )}
    </div>
  );
}