/**
 * TransformIQ — Error state component.
 *
 * Displays a user-readable error message with an optional retry action.
 */
import { cn } from "@/lib/utils";

interface ErrorStateProps {
  /** The error message to display. */
  message: string;
  /** Optional retry callback. */
  onRetry?: () => void;
  /** Additional Tailwind classes. */
  className?: string;
}

export function ErrorState({ message, onRetry, className }: ErrorStateProps) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center",
        className,
      )}
    >
      {/* Icon */}
      <svg
        aria-hidden="true"
        xmlns="http://www.w3.org/2000/svg"
        className="h-8 w-8 text-destructive"
        fill="none"
        viewBox="0 0 24 24"
        stroke="currentColor"
        strokeWidth={1.5}
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"
        />
      </svg>

      {/* Message */}
      <p className="text-sm text-destructive">{message}</p>

      {/* Retry */}
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-1 rounded-md border border-destructive/40 bg-background px-4 py-1.5 text-xs font-medium text-destructive hover:bg-destructive/10 transition-colors"
        >
          Try again
        </button>
      )}
    </div>
  );
}
