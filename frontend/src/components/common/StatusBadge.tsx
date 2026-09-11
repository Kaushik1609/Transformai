/**
 * TransformIQ — Status Badge component.
 *
 * A small inline chip for displaying job/service status values.
 */
import { cn } from "@/lib/utils";

export type BadgeVariant =
  | "default"
  | "success"
  | "warning"
  | "error"
  | "info"
  | "muted";

interface StatusBadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
}

const variantClasses: Record<BadgeVariant, string> = {
  default:
    "bg-primary/10 text-primary border-primary/20",
  success:
    "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-400 dark:border-green-800",
  warning:
    "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/30 dark:text-yellow-400 dark:border-yellow-800",
  error:
    "bg-destructive/10 text-destructive border-destructive/20",
  info:
    "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/30 dark:text-blue-400 dark:border-blue-800",
  muted:
    "bg-muted text-muted-foreground border-border",
};

export function StatusBadge({
  children,
  variant = "default",
  className,
}: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "label-mono-sm inline-flex items-center rounded-full border px-2 py-1 uppercase",
        variantClasses[variant],
        className,
      )}
    >
      {children}
    </span>
  );
}
