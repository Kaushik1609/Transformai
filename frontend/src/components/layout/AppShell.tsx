/**
 * TransformIQ — Application shell.
 *
 * Provides the global layout with the left sidebar, a top bar showing the page
 * title and actions, and a main content area. Desktop keeps a persistent
 * sidebar; mobile/tablet switches to a drawer.
 */
"use client";

import { ReactNode } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { LogoMark } from "@/components/brand";
import { RequireAuth } from "@/components/auth";
import SidebarNav from "./Sidebar";

interface AppShellProps {
  children?: ReactNode;
  /** Page title shown in the top bar. */
  title?: string;
  /** Optional secondary heading detail (e.g. a project name). */
  subtitle?: string;
  /** Right-side top bar actions (buttons/links). */
  actions?: ReactNode;
  /** Optional inspector rail (pinned right dock on xl+). */
  inspector?: ReactNode;
  /** Additional classes for the main area. */
  mainClassName?: string;
  /** Active nav section override. */
  active?: string;
}

export function AppShell({
  children,
  title,
  subtitle,
  actions,
  inspector,
  mainClassName,
  active,
}: AppShellProps) {
  return (
    <RequireAuth>
      <div className="flex min-h-screen bg-background">
      {/* Persistent sidebar (desktop) + hamburger/drawer (mobile) */}
      <SidebarNav active={active} />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface-elevated/60 px-4 backdrop-blur supports-[backdrop-filter]:bg-surface-elevated/40 sm:px-6">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            {title ? (
              <div className="ml-10 min-w-0 lg:ml-0">
                <h1 className="truncate text-lg font-semibold tracking-tight text-foreground">
                  {title}
                </h1>
                {subtitle && (
                  <p className="truncate text-xs text-muted-foreground">
                    {subtitle}
                  </p>
                )}
              </div>
            ) : (
              <Link
                href="/"
                className="ml-10 flex items-center gap-2 text-lg font-semibold tracking-tight text-foreground lg:ml-0"
              >
                <LogoMark size={26} />
                <span>TransformIQ</span>
              </Link>
            )}
          </div>

          {actions && (
            <div className="flex shrink-0 items-center gap-2">{actions}</div>
          )}
        </header>

        <main
          className={cn(
            "mx-auto flex w-full flex-1 max-w-[1400px] flex-col px-4 py-6 sm:px-6",
            mainClassName,
          )}
        >
          {children}
        </main>
      </div>

      {/* Optional inspector dock (pinned right rail on xl+). */}
      {inspector && (
        <aside
          aria-label="Inspector"
          className="hidden w-96 shrink-0 border-l border-sidebar-border bg-surface-elevated/40 xl:block"
        >
          <div className="sticky top-0 max-h-screen overflow-y-auto p-4">
            {inspector}
          </div>
        </aside>
      )}
      </div>
    </RequireAuth>
  );
}

export default AppShell;
