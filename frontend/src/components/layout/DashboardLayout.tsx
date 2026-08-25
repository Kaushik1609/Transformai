/**
 * TransformIQ — Dashboard Layout shell.
 *
 * Wraps all dashboard pages with the standard Header and a centred
 * main content area with a max-width constraint.
 */
import { Header } from "./Header";
import { cn } from "@/lib/utils";

interface DashboardLayoutProps {
  children: React.ReactNode;
  /** Optional additional Tailwind classes for the <main> element. */
  mainClassName?: string;
}

export function DashboardLayout({
  children,
  mainClassName,
}: DashboardLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col bg-background">
      <Header />
      <main
        className={cn(
          "mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6",
          mainClassName,
        )}
      >
        {children}
      </main>
    </div>
  );
}
