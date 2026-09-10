/**
 * TransformIQ — Application sidebar (navigation shell).
 *
 * Persistent on desktop, drawer on tablet/mobile, collapsible to icon-only on
 * desktop. Provides the primary application navigation used across all
 * authenticated pages.
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useModalA11y } from "@/lib/useModalA11y";
import { LogoMark } from "@/components/brand";
import {
  Home,
  Folder,
  History,
  Settings,
  HelpCircle,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  Plus,
  Menu,
  X,
  LogOut,
} from "lucide-react";
import {
  getDevSession,
  getAuthUser,
  clearDevSession,
  clearAuthToken,
} from "@/lib/auth";
import { authApi } from "@/lib/api";
import { clearQuickProjectId } from "@/lib/quickWorkspace";

interface SidebarProps {
  /** Active section, used to highlight nav. Defaults to derive from pathname. */
  active?: string;
  /** When provided as a mobile drawer trigger, renders a toggle button. */
  mobile?: boolean;
}

const NAV_ITEMS = [
  { href: "/", label: "Home", icon: Home },
  { href: "/projects", label: "Projects", icon: Folder },
  { href: "/history", label: "History", icon: History },
];

const BOTTOM_ITEMS = [
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

/** Resolve the identity block truthfully: real account > dev session. */
function identity() {
  const user = getAuthUser();
  if (user) {
    return {
      name: user.name,
      email: user.email,
      initial: user.name.trim().charAt(0).toUpperCase() || "U",
      subtitle: "Signed in",
    };
  }
  const session = getDevSession();
  if (session) {
    return {
      name: session.name,
      email: session.email,
      initial: session.name.trim().charAt(0).toUpperCase() || "D",
      subtitle: "Development identity",
    };
  }
  return {
    name: "Development User",
    email: "dev@transformiq.local",
    initial: "D",
    subtitle: "Development identity",
  };
}

export function SidebarNav({ active }: { active?: string }) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  const resolveActive = (href: string) =>
    active ? active === href : isActive(pathname, href);

  return (
    <>
      {/* Desktop / tablet persistent sidebar */}
      <aside
        className={cn(
          "hidden shrink-0 flex-col border-r border-sidebar-border bg-sidebar-bg lg:flex",
          collapsed ? "w-[72px]" : "w-[248px]",
        )}
        aria-label="Primary navigation"
      >
        <div
          className={cn(
            "flex items-center gap-2.5 px-4 py-4",
            collapsed && "justify-center px-2",
          )}
        >
          <Link href="/" aria-label="TransformIQ home" className="flex items-center gap-2.5">
            <LogoMark size={30} />
            {!collapsed && (
              <span className="text-[15px] font-semibold tracking-tight text-foreground">
                TransformIQ
              </span>
            )}
          </Link>
        </div>

        <div className="px-3 pb-2">
          <Link
            href="/projects"
            className={cn(
              "flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90",
              collapsed && "justify-center px-2",
            )}
            title={collapsed ? "New Project" : undefined}
          >
            <Plus className="h-4 w-4" aria-hidden="true" />
            {!collapsed && <span>New Project</span>}
          </Link>
        </div>

        <nav className="flex-1 space-y-1 px-3 pt-3">
          {!collapsed && (
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              Workspace
            </p>
          )}
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const isCurrent = resolveActive(href);
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                aria-label={collapsed ? label : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  collapsed && "justify-center px-2",
                  isCurrent
                    ? "bg-primary/10 font-medium text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
                aria-current={isCurrent ? "page" : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </nav>

        <div className="space-y-1 border-t border-sidebar-border px-3 py-3">
          {!collapsed && (
            <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
              System
            </p>
          )}
          {BOTTOM_ITEMS.map(({ href, label, icon: Icon }) => {
            const isCurrent = resolveActive(href);
            return (
              <Link
                key={href}
                href={href}
                title={collapsed ? label : undefined}
                aria-label={collapsed ? label : undefined}
                className={cn(
                  "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  collapsed && "justify-center px-2",
                  isCurrent
                    ? "bg-primary/10 font-medium text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                )}
                aria-current={isCurrent ? "page" : undefined}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {!collapsed && <span>{label}</span>}
              </Link>
            );
          })}
        </div>

        {/* Profile block */}
        <ProfileMenu collapsed={collapsed} />

        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="flex items-center justify-center gap-2 border-t border-sidebar-border py-2.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" aria-hidden="true" />
          ) : (
            <>
              <ChevronsLeft className="h-4 w-4" aria-hidden="true" />
              Collapse
            </>
          )}
        </button>
      </aside>

      {/* Mobile drawer */}
      <MobileDrawer active={active} />
    </>
  );
}

function ProfileMenu({ collapsed }: { collapsed: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  const viewer = identity();
  const { name, email, initial, subtitle } = viewer;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort server-side revocation; local cleanup still proceeds.
    }
    // Remove the real access token (and the stored identity) so protected
    // routes cannot reopen without signing in again. Dev-session and quick
    // workspace state are cleared afterwards for parity.
    clearAuthToken();
    clearDevSession();
    clearQuickProjectId();
    setOpen(false);
    router.replace("/login");
  };

  return (
    <div
      ref={menuRef}
      className={cn(
        "relative border-t border-sidebar-border",
        collapsed && "flex justify-center",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className={cn(
          "flex w-full items-center gap-2.5 px-3 py-3 text-left transition-colors hover:bg-muted/40",
          collapsed && "justify-center px-2",
        )}
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary-foreground">
          {initial}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-foreground">
                {email}
              </span>
              <span className="block truncate text-[11px] text-muted-foreground">
                {subtitle}
              </span>
            </span>
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                open && "rotate-180",
              )}
              aria-hidden="true"
            />
          </>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account menu actions"
          className="absolute bottom-full left-3 z-50 mb-1 w-60 overflow-hidden rounded-xl border border-border bg-popover p-1 shadow-xl"
        >
          <div className="px-3 pb-2 pt-2.5">
            <p className="truncate text-sm font-medium text-foreground">{name}</p>
            <p className="truncate text-xs text-muted-foreground">{email}</p>
            <p className="mt-1 text-[11px] text-muted-foreground/80">
              {subtitle}
            </p>
          </div>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            role="menuitem"
            onClick={handleLogout}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            Log out
          </button>
        </div>
      )}
    </div>
  );
}

function MobileDrawer({ active }: { active?: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const drawerRef = useRef<HTMLDivElement>(null);

  useModalA11y(open, () => setOpen(false), drawerRef);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const resolveActive = (href: string) =>
    active ? active === href : isActive(pathname, href);

  const viewer = identity();
  const { email, initial } = viewer;

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort server-side revocation; local cleanup still proceeds.
    }
    clearAuthToken();
    clearDevSession();
    clearQuickProjectId();
    setOpen(false);
    router.replace("/login");
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground lg:hidden"
        aria-label="Open navigation"
      >
        <Menu className="h-5 w-5" aria-hidden="true" />
      </button>

      {open && (
        <div
          ref={drawerRef}
          tabIndex={-1}
          className="fixed inset-0 z-50 lg:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Navigation"
        >
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-sidebar-border bg-sidebar-bg">
            <div className="flex items-center justify-between px-4 py-4">
              <Link href="/" className="flex items-center gap-2.5">
                <LogoMark size={30} />
                <span className="text-[15px] font-semibold text-foreground">
                  TransformIQ
                </span>
              </Link>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-md p-1.5 text-muted-foreground hover:text-foreground"
                aria-label="Close navigation"
              >
                <X className="h-5 w-5" aria-hidden="true" />
              </button>
            </div>

            <div className="px-3 pb-2">
              <Link
                href="/projects"
                className="flex items-center justify-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
                New Project
              </Link>
            </div>

            <nav className="flex-1 space-y-1 px-3 pt-3">
              <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
                Workspace
              </p>
              {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
                const isCurrent = resolveActive(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm",
                      isCurrent
                        ? "bg-primary/10 font-medium text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                    )}
                    aria-current={isCurrent ? "page" : undefined}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span>{label}</span>
                  </Link>
                );
              })}
            </nav>

            <div className="space-y-1 border-t border-sidebar-border px-3 py-3">
              <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/70">
                System
              </p>
              {BOTTOM_ITEMS.map(({ href, label, icon: Icon }) => {
                const isCurrent = resolveActive(href);
                return (
                  <Link
                    key={href}
                    href={href}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm",
                      isCurrent
                        ? "bg-primary/10 font-medium text-primary-foreground"
                        : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
                    )}
                    aria-current={isCurrent ? "page" : undefined}
                  >
                    <Icon className="h-4 w-4" aria-hidden="true" />
                    <span>{label}</span>
                  </Link>
                );
              })}
            </div>

            <div className="border-t border-sidebar-border px-3 py-3">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-sm font-semibold text-primary-foreground">
                  {initial}
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-foreground">
                    {email}
                  </p>
                  <p className="truncate text-[11px] text-muted-foreground">
                    {viewer.subtitle}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="mt-2 flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <LogOut className="h-4 w-4" aria-hidden="true" />
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

export default SidebarNav;
