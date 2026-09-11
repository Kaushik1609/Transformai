/**
 * TransformIQ — Application shell (Stitch enterprise layout).
 *
 * Mirrors the Stitch reference shell: a fixed navigation rail on the left
 * (collapsible on desktop, drawer on mobile) and a fixed top bar running from
 * the rail edge across the content column. The main column is offset by the
 * rail width and padded below the top bar.
 */
"use client";

import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { RequireAuth } from "@/components/auth";
import SidebarNav from "./Sidebar";
import { AppHeader } from "./AppHeader";

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
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <RequireAuth>
      <div className="flex min-h-screen bg-background text-foreground">
        {/* Fixed rail (desktop) + hamburger/drawer (mobile) */}
        <SidebarNav
          active={active}
          collapsed={collapsed}
          onCollapsedChange={setCollapsed}
          mobileOpen={mobileOpen}
          onMobileClose={() => setMobileOpen(false)}
        />

        {/* Content column, offset by the rail width on desktop */}
        <div
          className={cn(
            "flex min-w-0 flex-1 flex-col transition-[padding] duration-200",
            collapsed ? "lg:pl-16" : "lg:pl-64",
          )}
        >
          {/* Fixed Stitch top bar */}
          <AppHeader
            title={title}
            subtitle={subtitle}
            actions={actions}
            collapsed={collapsed}
            onToggleMobileMenu={() => setMobileOpen(true)}
          />

          <main
            className={cn(
              "mx-auto flex w-full flex-1 max-w-[1440px] flex-col px-4 py-6 pt-20 sm:px-6",
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
            className="hidden w-96 shrink-0 border-l border-border bg-surface-container-low/40 xl:block"
          >
            <div className="sticky top-16 max-h-[calc(100vh-4rem)] overflow-y-auto p-4">
              {inspector}
            </div>
          </aside>
        )}
      </div>
    </RequireAuth>
  );
}

export default AppShell;