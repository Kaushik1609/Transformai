/**
 * TransformIQ — Loading state component.
 *
 * Simple, accessible spinner used wherever async operations are in flight.
 * Accepts an optional label for screen reader context.
 */
import { cn } from "@/lib/utils";

interface LoadingSpinnerProps {
  /** Additional Tailwind classes applied to the wrapper. */
  className?: string;
  /** Accessible label shown only to screen readers. */
  label?: string;
  /** Size variant. Defaults to "md". */
  size?: "sm" | "md" | "lg";
}

const sizeClasses: Record<NonNullable<LoadingSpinnerProps["size"]>, string> = {
  sm: "h-4 w-4 border-2",
  md: "h-6 w-6 border-2",
  lg: "h-10 w-10 border-4",
};

export function LoadingSpinner({
  className,
  label = "Loading…",
  size = "md",
}: LoadingSpinnerProps) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cn("inline-flex items-center justify-center", className)}
    >
      <span
        className={cn(
          "animate-spin rounded-full border-border border-t-primary",
          sizeClasses[size],
        )}
      />
      <span className="sr-only">{label}</span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Full-page loading overlay
// ---------------------------------------------------------------------------

interface PageLoadingProps {
  message?: string;
}

export function PageLoading({ message = "Loading…" }: PageLoadingProps) {
  return (
    <div className="flex min-h-[200px] flex-col items-center justify-center gap-3 p-8">
      <LoadingSpinner size="lg" label={message} />
      <p className="text-sm text-muted-foreground">{message}</p>
    </div>
  );
}
