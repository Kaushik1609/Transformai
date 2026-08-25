/**
 * TransformIQ — Empty state component.
 *
 * Shown when a list or content area has no items to display.
 */
import { cn } from "@/lib/utils";

interface EmptyStateProps {
  /** Short headline. */
  title: string;
  /** Supportive description text. */
  description?: string;
  /** Optional call-to-action element (e.g., a Button). */
  action?: React.ReactNode;
  /** Additional Tailwind classes. */
  className?: string;
}

export function EmptyState({
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-dashed border-border bg-muted/30 p-10 text-center",
        className,
      )}
    >
      {/* Icon */}
      <svg
        aria-hidden="true"
        xmlns="http://www.w3.org/2000/svg"
        className="h-10 w-10 text-muted-foreground/50"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.2}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m6.75 12-3-3m0 0-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
        />
      </svg>

      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </div>

      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
