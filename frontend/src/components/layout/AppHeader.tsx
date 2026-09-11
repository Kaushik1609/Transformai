/**
 * TransformIQ — Enterprise Application Header (Stitch Specification).
 *
 * Fixed top bar (h-16 / 64px) with:
 *   - Workspace selector dropdown (bound to real user projects)
 *   - Global search input with Cmd+K shortcut
 *   - Notifications flyout with real job status
 *   - Theme switcher (Light / Dark / System)
 *   - Real user avatar and account trigger
 *   - Mobile drawer toggle
 */
"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  type ProjectResponse,
  type TransformationJobResponse,
  projectsApi,
  transformationsApi,
} from "@/lib/api";
import { getAuthUser, getDevSession } from "@/lib/auth";
import { useTheme } from "@/components/theme";
import { cn } from "@/lib/utils";
import {
  Building2,
  Search,
  Bell,
  Sun,
  Moon,
  ChevronDown,
  Menu,
  CheckCircle2,
  ExternalLink,
  Plus,
} from "lucide-react";

interface AppHeaderProps {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  collapsed?: boolean;
  onToggleMobileMenu: () => void;
}

export function AppHeader({
  title,
  subtitle,
  actions,
  collapsed = false,
  onToggleMobileMenu,
}: AppHeaderProps) {
  const router = useRouter();
  const { theme, resolved, setTheme } = useTheme();

  // ---- Workspace dropdown state -------------------------------------------
  const [workspaceOpen, setWorkspaceOpen] = useState(false);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [selectedWorkspaceName, setSelectedWorkspaceName] = useState(
    "All projects",
  );
  const workspaceRef = useRef<HTMLDivElement>(null);

  // ---- Notifications popover state ----------------------------------------
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [recentJobs, setRecentJobs] = useState<TransformationJobResponse[]>([]);
  const notificationsRef = useRef<HTMLDivElement>(null);

  // ---- Search state -------------------------------------------------------
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  // ---- Real identity ------------------------------------------------------
  const user = getAuthUser();
  const devSession = getDevSession();
  const displayName = user?.name || devSession?.name || "Enterprise Analyst";
  const userInitial = displayName.trim().charAt(0).toUpperCase() || "K";

  // Load real projects only when workspace dropdown is opened
  useEffect(() => {
    if (!workspaceOpen) return;
    let cancelled = false;
    projectsApi
      .list()
      .then((res) => {
        if (!cancelled && Array.isArray(res?.data)) {
          setProjects(res.data);
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [workspaceOpen]);

  // Load real recent transformations only when notifications dropdown is opened
  useEffect(() => {
    if (!notificationsOpen) return;
    let cancelled = false;
    projectsApi
      .list()
      .then((projRes) => {
        if (cancelled || !Array.isArray(projRes?.data) || projRes.data.length === 0) return;
        return transformationsApi.listByProject(projRes.data[0].id);
      })
      .then((jobsRes) => {
        if (!cancelled && Array.isArray(jobsRes?.data)) {
          setRecentJobs(jobsRes.data.slice(0, 5));
        }
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [notificationsOpen]);

  // Global Cmd+K keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchInputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Close popovers on outside click
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (
        workspaceRef.current &&
        !workspaceRef.current.contains(e.target as Node)
      ) {
        setWorkspaceOpen(false);
      }
      if (
        notificationsRef.current &&
        !notificationsRef.current.contains(e.target as Node)
      ) {
        setNotificationsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchQuery.trim()) {
      router.push(`/history?search=${encodeURIComponent(searchQuery.trim())}`);
    }
  };

  const toggleTheme = () => {
    const next = resolved === "dark" ? "light" : "dark";
    setTheme(next);
  };

  return (
    <header
      className={cn(
        "fixed right-0 top-0 z-40 flex h-16 items-center justify-between gap-3 border-b border-border bg-surface/85 px-4 shadow-[0_1px_8px_rgba(0,0,0,0.04)] backdrop-blur-xl transition-[left] duration-200 sm:px-6",
        collapsed ? "lg:left-16" : "lg:left-64",
        "left-0",
      )}
    >
      {/* Left: Mobile hamburger + Workspace selector & Search */}
      <div className="flex flex-1 items-center gap-3 min-w-0 max-w-2xl">
        {/* Mobile menu trigger */}
        <button
          type="button"
          onClick={onToggleMobileMenu}
          className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border bg-surface-container p-1 text-on-surface hover:bg-surface-container-high lg:hidden shrink-0"
          aria-label="Open navigation"
        >
          <Menu className="h-5 w-5" aria-hidden="true" />
        </button>

        {/* Workspace Selector Dropdown */}
        <div ref={workspaceRef} className="relative shrink-0 hidden sm:block">
          <button
            type="button"
            onClick={() => setWorkspaceOpen(!workspaceOpen)}
            className="flex items-center gap-2 rounded bg-surface-container px-3 py-1.5 text-xs font-medium text-on-surface transition-colors hover:bg-surface-container-high"
            aria-expanded={workspaceOpen}
            aria-haspopup="listbox"
          >
            <Building2 className="h-4 w-4 text-secondary-fixed-dim shrink-0" aria-hidden="true" />
            <span className="truncate max-w-[180px] md:max-w-[240px]">
              {title || selectedWorkspaceName}
            </span>
            <ChevronDown
              className={cn(
                "h-3.5 w-3.5 text-muted-foreground transition-transform shrink-0",
                workspaceOpen && "rotate-180",
              )}
              aria-hidden="true"
            />
          </button>

          {workspaceOpen && (
            <div
              role="listbox"
              aria-label="Workspaces"
              className="absolute left-0 top-full mt-2 w-72 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-100"
            >
              <div className="px-3 py-2 text-[10px] font-label-mono-sm uppercase text-muted-foreground">
                Switch Workspace
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedWorkspaceName("All projects");
                  setWorkspaceOpen(false);
                  router.push("/");
                }}
                className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-xs hover:bg-surface-container-high transition-colors"
              >
                <div className="min-w-0">
                  <div className="font-medium text-foreground truncate">
                    All projects
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    Browse every workspace
                  </div>
                </div>
                {selectedWorkspaceName === "All projects" && (
                  <CheckCircle2 className="h-3.5 w-3.5 text-secondary-fixed-dim shrink-0" />
                )}
              </button>

              <div className="my-1 h-px bg-border" />
              <div className="px-3 py-1 text-[10px] font-label-mono-sm uppercase text-muted-foreground">
                Project Pods ({projects.length})
              </div>

              <div className="max-h-48 overflow-y-auto">
                {projects.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => {
                      setSelectedWorkspaceName(p.name);
                      setWorkspaceOpen(false);
                      router.push(`/projects/${p.id}`);
                    }}
                    className="flex w-full items-center justify-between rounded-md px-3 py-1.5 text-left text-xs hover:bg-surface-container-high transition-colors"
                  >
                    <span className="truncate text-foreground">{p.name}</span>
                    <span className="label-mono-xs text-muted-foreground shrink-0">
                      Pod
                    </span>
                  </button>
                ))}
              </div>

              <div className="my-1 h-px bg-border" />
              <Link
                href="/projects"
                onClick={() => setWorkspaceOpen(false)}
                className="flex items-center gap-2 rounded-md px-3 py-1.5 text-xs text-secondary-fixed-dim hover:bg-surface-container-high transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Manage All Projects</span>
              </Link>
            </div>
          )}
        </div>

        {/* Global Search Box (Cmd + K) */}
        <form
          onSubmit={handleSearchSubmit}
          className="flex flex-1 items-center gap-2 rounded bg-surface-container-lowest px-3 py-1.5 border border-transparent focus-within:border-border max-w-md shadow-inner"
        >
          <Search className="h-4 w-4 text-outline shrink-0" aria-hidden="true" />
          <input
            ref={searchInputRef}
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search sources, transformations, artifacts... (Cmd + K)"
            aria-label="Search across workspace"
            className="w-full bg-transparent text-xs text-foreground placeholder:text-outline focus:outline-none"
          />
          <kbd className="hidden sm:inline-block rounded bg-surface-container-high px-1.5 py-0.5 text-[10px] font-label-mono-sm text-muted-foreground">
            ⌘K
          </kbd>
        </form>
      </div>

      {/* Right: Compliance Pill + Notifications + Theme Switcher + Profile Avatar */}
      <div className="flex items-center gap-3 shrink-0">
        {actions && (
          <div className="hidden sm:flex items-center gap-2 mr-1">
            {actions}
          </div>
        )}

        {/* Notifications Popover Trigger */}
        <div ref={notificationsRef} className="relative">
          <button
            type="button"
            onClick={() => setNotificationsOpen(!notificationsOpen)}
            className="relative rounded p-1.5 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
            aria-label="Notifications"
            aria-expanded={notificationsOpen}
          >
            <Bell className="h-4 w-4" aria-hidden="true" />
            <span className="absolute right-1 top-1 h-2 w-2 rounded-full bg-secondary" />
          </button>

          {notificationsOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 overflow-hidden rounded-lg border border-border bg-popover p-3 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-100">
              <div className="flex items-center justify-between pb-2 border-b border-border">
                <span className="text-xs font-semibold text-foreground">
                  System Notifications
                </span>
                <span className="font-label-mono-sm text-[10px] text-secondary-fixed-dim">
                  Live Engine
                </span>
              </div>
              <div className="mt-2 space-y-2">
                {recentJobs.length > 0 ? (
                  recentJobs.map((j) => (
                    <Link
                      key={j.id}
                      href="/history"
                      onClick={() => setNotificationsOpen(false)}
                      className="flex items-start gap-2 rounded p-1.5 text-xs hover:bg-surface-container-high transition-colors"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        <p className="font-medium text-foreground truncate">
                          Transformation {j.id.slice(0, 8)} completed
                        </p>
<p className="text-[10px] text-muted-foreground font-label-mono-sm">
  Status: {j.status}
</p>
                      </div>
                    </Link>
                  ))
                ) : (
                  <p className="text-xs text-muted-foreground py-2 text-center">
                    All transformation pipelines healthy.
                  </p>
                )}
              </div>
              <div className="pt-2 mt-2 border-t border-border flex justify-end">
                <Link
                  href="/history"
                  onClick={() => setNotificationsOpen(false)}
                  className="text-[11px] text-secondary-fixed-dim hover:underline flex items-center gap-1"
                >
                  <span>View History</span>
                  <ExternalLink className="h-3 w-3" />
                </Link>
              </div>
            </div>
          )}
        </div>

        {/* Theme Toggle (Light / Dark switch) */}
        <button
          type="button"
          onClick={toggleTheme}
          className="rounded p-1.5 text-on-surface-variant transition-colors hover:bg-surface-container hover:text-on-surface"
          aria-label={`Switch to ${resolved === "dark" ? "light" : "dark"} theme`}
          title={`Switch to ${resolved === "dark" ? "light" : "dark"} theme`}
        >
          {resolved === "dark" ? (
            <Sun className="h-4 w-4" aria-hidden="true" />
          ) : (
            <Moon className="h-4 w-4" aria-hidden="true" />
          )}
        </button>

        {/* Profile Avatar Chip */}
        <Link
          href="/settings"
          className="flex items-center gap-2 pl-1 group"
          title={`Signed in as ${displayName}`}
          aria-label="Go to settings"
        >
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-surface-container-highest font-label-mono-md text-label-mono-md text-primary group-hover:ring-2 group-hover:ring-primary/40 transition-all">
            {userInitial}
          </div>
        </Link>
      </div>
    </header>
  );
}
