/**
 * TransformIQ — Section card.
 *
 * A bordered container with an optional title — used to group the workspace
 * steps (source, configuration, outputs) and output panels.
 */
import { cn } from "@/lib/utils";

interface SectionCardProps {
  title?: string;
  description?: string;
  className?: string;
  bodyClassName?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}

export function SectionCard({
  title,
  description,
  className,
  bodyClassName,
  right,
  children,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        "rounded-lg border border-border bg-background",
        className,
      )}
    >
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
          <div className="space-y-0.5">
            {title && (
              <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            )}
            {description && (
              <p className="text-xs text-muted-foreground">{description}</p>
            )}
          </div>
          {right}
        </header>
      )}
      <div className={cn("px-4 py-4", bodyClassName)}>{children}</div>
    </section>
  );
}