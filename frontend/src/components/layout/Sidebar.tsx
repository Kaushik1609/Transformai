/**
 * TransformIQ — Enterprise Application Sidebar / Rail (Stitch Specification).
 *
 * Fixed navigation rail on desktop (w-64 expanded, w-16 collapsed) and responsive
 * overlay drawer on mobile. Implements:
 *   - Logo mark ("T" emblem + "TransformIQ" + "ENTERPRISE" pill)
 *   - High-contrast "+ Create Transformation" CTA button
 *   - Controlled navigation: Home (/), Projects (/projects), History (/history),
 *     Security Activity (/security), Settings (/settings)
 *   - Live operational status indicator: "Pipeline Active · Grounded RAG"
 *   - Profile card with real authenticated identity and accessible Account Menu
 */
"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState, useCallback, useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import { useModalA11y } from "@/lib/useModalA11y";
import {
  LayoutGrid,
  Folder,
  History,
  ShieldCheck,
  Settings,
  ChevronsLeft,
  ChevronsRight,
  ChevronDown,
  PlusCircle,
  Plus,
  X,
  LogOut,
  Sparkles,
} from "lucide-react";
import {
  getDevSession,
  getAuthUser,
  clearDevSession,
  clearAuthToken,
} from "@/lib/auth";
import { authApi } from "@/lib/api";
import { clearQuickProjectId } from "@/lib/quickWorkspace";
import { LogoMark } from "@/components/brand";

interface SidebarProps {
  /** Active section, used to highlight nav. Defaults to derive from pathname. */
  active?: string;
  /** Collapsed rail state (controlled by the app shell). */
  collapsed?: boolean;
  /** Collapse toggler. */
  onCollapsedChange?: (collapsed: boolean) => void;
  /** Mobile drawer visibility control. */
  mobileOpen?: boolean;
  /** Mobile drawer close handler. */
  onMobileClose?: () => void;
}

const NAV_ITEMS = [
  { href: "/", label: "Home", icon: LayoutGrid },
  { href: "/projects", label: "Projects", icon: Folder },
  { href: "/history", label: "History", icon: History },
  { href: "/security", label: "Security Activity", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname.startsWith(href);
}

/**
 * Resolve the identity block truthfully: real account > explicit development
 * identity (only when the bypass is active) > neutral "Signed in".
 */
function identity() {
  const user = getAuthUser();
  if (user) {
    return {
      name: user.name,
      email: user.email,
      initial: user.name.trim().charAt(0).toUpperCase() || "U",
      subtitle: user.role ? `Role: ${user.role}` : "Enterprise Operator",
    };
  }
  const session = getDevSession();
  const devBypass = process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === "true";
  if (session && devBypass) {
    return {
      name: session.name,
      email: session.email,
      initial: session.name.trim().charAt(0).toUpperCase() || "D",
      subtitle: "Development Identity",
    };
  }
  return {
    name: "Signed in",
    email: "",
    initial: "S",
    subtitle: "Enterprise Operator",
  };
}

export default function SidebarNav({
  active,
  collapsed: collapsedProp,
  onCollapsedChange,
  mobileOpen = false,
  onMobileClose,
}: SidebarProps) {
  const pathname = usePathname();
  const [collapsedInternal, setCollapsedInternal] = useState(false);
  const collapsed = collapsedProp ?? collapsedInternal;
  const setCollapsed = (next: boolean) => {
    setCollapsedInternal(next);
    onCollapsedChange?.(next);
  };

  const resolveActive = (href: string) =>
    active ? active === href : isActive(pathname, href);

  const navLinkClass = (isCurrent: boolean, iconOnly: boolean) =>
    cn(
      "flex items-center gap-3 rounded px-3 py-2 text-sm transition-colors font-medium",
      iconOnly && "justify-center px-2",
      isCurrent
        ? "bg-surface-container-high text-on-surface font-semibold shadow-sm"
        : "text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface",
    );

  return (
    <>
      {/* Desktop fixed rail */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 hidden flex-col justify-between bg-surface-container-low border-r border-border shadow-[0_1px_8px_rgba(0,0,0,0.04)] transition-[width] duration-200 lg:flex",
          collapsed ? "w-16" : "w-64",
        )}
        aria-label="Primary navigation"
      >
        <div className="flex flex-col">
          {/* Brand Header */}
          <div
            className={cn(
              "flex h-16 shrink-0 items-center justify-between px-4 border-b border-border/50",
              collapsed && "justify-center px-0",
            )}
          >
            <Link
              href="/"
              aria-label="KaryaSetu AI home"
              className={cn("flex items-center gap-2.5", collapsed && "gap-0")}
            >
              <LogoMark size={28} />
              {!collapsed && (
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="font-headline-sm text-headline-sm tracking-tight text-on-surface font-semibold">
                    KaryaSetu
                  </span>
                  <span className="font-label-mono-sm text-[10px] px-1.5 py-0.5 rounded bg-primary/20 text-primary font-bold">
                    AI
                  </span>
                </div>
              )}
            </Link>

            {!collapsed && (
              <div className="flex items-center gap-1.5">
                <span className="font-label-mono-sm text-label-mono-sm px-1.5 py-0.5 rounded bg-surface-container-highest text-secondary-fixed-dim uppercase font-semibold">
                  ENTERPRISE
                </span>
                <button
                  type="button"
                  onClick={() => setCollapsed(true)}
                  className="rounded p-1 text-muted-foreground hover:bg-surface-container hover:text-foreground transition-colors"
                  aria-label="Collapse sidebar"
                >
                  <ChevronsLeft className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
          </div>

          {/* Primary Action CTA Button */}
          <div className="px-3 pt-4 pb-2">
            <Link
              href="/create"
              className={cn(
                "flex items-center justify-center gap-2.5 rounded-lg bg-primary py-2.5 px-3 text-primary-foreground headline-sm shadow-[0_0_16px_rgba(37,99,235,0.4)] transition-all hover:bg-primary/90 active:scale-[0.98]",
                collapsed && "px-0 py-2.5",
              )}
              title={collapsed ? "+ Create Transformation" : undefined}
              aria-label={collapsed ? "+ Create Transformation" : undefined}
            >
              <Plus className="h-4 w-4 stroke-[3] shrink-0" aria-hidden="true" />
              {!collapsed && <span>+ Create Transformation</span>}
            </Link>
          </div>

          {/* Navigation Links */}
          <nav className="flex flex-col gap-1 px-3 pt-2">
            {!collapsed && (
              <p className="label-mono-xs px-3 pb-1 pt-2 text-muted-foreground uppercase">
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
                  className={navLinkClass(isCurrent, collapsed)}
                  aria-current={isCurrent ? "page" : undefined}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {!collapsed && (
                    <span className="font-body-md text-body-md">{label}</span>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Bottom Rail Section */}
        <div className="p-3 flex flex-col gap-3 border-t border-border/50">
          {/* Operational Status Ticker */}
          {!collapsed ? (
            <div className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-surface-container-lowest">
              <span className="h-2 w-2 rounded-full bg-secondary animate-pulse shrink-0" />
              <span className="font-label-mono-sm text-label-mono-sm text-on-surface-variant truncate">
                Pipeline Active · Grounded RAG
              </span>
            </div>
          ) : (
            <div
              className="flex items-center justify-center py-1.5 rounded bg-surface-container-lowest"
              title="Pipeline Active · Grounded RAG"
            >
              <span className="h-2 w-2 rounded-full bg-secondary animate-pulse" />
            </div>
          )}

          {/* Profile Card & Account Menu */}
          <ProfileCard collapsed={collapsed} />

          {/* Collapsed expand toggle */}
          {collapsed && (
            <button
              type="button"
              onClick={() => setCollapsed(false)}
              className="flex w-full items-center justify-center rounded p-1.5 text-muted-foreground hover:bg-surface-container hover:text-foreground transition-colors"
              aria-label="Expand sidebar"
            >
              <ChevronsRight className="h-4 w-4" />
            </button>
          )}
        </div>
      </aside>

      {/* Responsive Mobile Drawer */}
      <MobileDrawer
        open={mobileOpen}
        onClose={onMobileClose}
        active={active}
      />
    </>
  );
}

function ProfileCard({ collapsed }: { collapsed: boolean }) {
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

  const handleLogout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort server-side revocation
    }
    clearAuthToken();
    clearDevSession();
    clearQuickProjectId();
    setOpen(false);
    router.replace("/login");
  }, [router]);

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className={cn(
          "flex w-full items-center justify-between p-2 rounded bg-surface-container hover:bg-surface-container-high transition-colors text-left",
          collapsed && "justify-center p-2",
        )}
      >
        <div className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center font-label-mono-md text-label-mono-md text-primary shrink-0">
            {initial}
          </div>
          {!collapsed && (
            <div className="flex flex-col min-w-0">
              <span className="font-headline-sm text-body-sm text-on-surface leading-tight truncate">
                {name}
              </span>
              <span className="font-caption text-caption text-on-surface-variant leading-tight truncate">
                {subtitle}
              </span>
            </div>
          )}
        </div>
        {!collapsed && (
          <ChevronDown
            className={cn(
              "h-4 w-4 text-on-surface-variant transition-transform shrink-0",
              open && "rotate-180",
            )}
            aria-hidden="true"
          />
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account menu actions"
          className="absolute bottom-full left-0 z-50 mb-2 w-60 overflow-hidden rounded-lg border border-border bg-popover p-1 shadow-2xl animate-in fade-in zoom-in-95 duration-100"
        >
          <div className="px-3 pb-2 pt-2.5">
            <p className="truncate text-sm font-semibold text-foreground">{name}</p>
            {email && (
              <p className="truncate text-xs text-muted-foreground">{email}</p>
            )}
            <p className="mt-1 text-[11px] font-label-mono-sm text-secondary-fixed-dim">
              {subtitle}
            </p>
          </div>
          <div className="my-1 h-px bg-border" />
          <Link
            href="/settings"
            onClick={() => setOpen(false)}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-on-surface hover:bg-surface-container-high transition-colors"
          >
            <Settings className="h-4 w-4" />
            <span>Account Settings</span>
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => void handleLogout()}
            className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-xs text-destructive hover:bg-destructive/10 transition-colors"
          >
            <LogOut className="h-4 w-4" aria-hidden="true" />
            <span>Log out</span>
          </button>
        </div>
      )}
    </div>
  );
}

function MobileDrawer({
  open,
  onClose,
  active,
}: {
  open: boolean;
  onClose?: () => void;
  active?: string;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const drawerRef = useRef<HTMLDivElement>(null);

  useModalA11y(open, onClose ?? (() => {}), drawerRef);

  const prevPath = useRef(pathname);
  useEffect(() => {
    if (prevPath.current !== pathname) {
      prevPath.current = pathname;
      onClose?.();
    }
  }, [pathname, onClose]);

  const resolveActive = (href: string) =>
    active ? active === href : isActive(pathname, href);

  const viewer = identity();
  const { name, email, initial, subtitle } = viewer;

  const handleLogout = async () => {
    try {
      await authApi.logout();
    } catch {
      // Best-effort revocation
    }
    clearAuthToken();
    clearDevSession();
    clearQuickProjectId();
    onClose?.();
    router.replace("/login");
  };

  if (!open) return null;

  return (
    <div
      ref={drawerRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-label="Navigation drawer"
      className="fixed inset-0 z-50 flex lg:hidden"
    >
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Slide-over panel */}
      <div className="relative z-10 flex h-full w-72 flex-col justify-between bg-surface-container-low border-r border-border p-4 shadow-2xl animate-in slide-in-from-left duration-200">
        <div className="flex flex-col">
          {/* Header */}
          <div className="flex h-12 items-center justify-between pb-3 border-b border-border">
            <Link
              href="/"
              onClick={onClose}
              className="flex items-center gap-2.5"
            >
              <LogoMark size={28} />
              <span className="font-headline-sm text-headline-sm tracking-tight text-on-surface font-semibold">
                KaryaSetu
              </span>
              <span className="font-label-mono-sm text-[9px] px-1.5 py-0.5 rounded bg-primary/20 text-primary font-bold">
                AI
              </span>
              <span className="font-label-mono-sm text-[9px] px-1.5 py-0.5 rounded bg-surface-container-highest text-secondary-fixed-dim uppercase font-semibold ml-1">
                ENTERPRISE
              </span>
            </Link>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-muted-foreground hover:bg-surface-container hover:text-foreground"
              aria-label="Close navigation drawer"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Primary CTA */}
          <div className="py-4">
            <Link
              href="/create"
              onClick={onClose}
              className="flex w-full items-center justify-center gap-2.5 rounded-lg bg-primary py-2.5 px-3 text-primary-foreground headline-sm shadow-[0_0_16px_rgba(37,99,235,0.4)] transition-all hover:bg-primary/90 active:scale-[0.98]"
            >
              <Plus className="h-4 w-4 stroke-[3] shrink-0" aria-hidden="true" />
              <span>+ Create Transformation</span>
            </Link>
          </div>

          {/* Navigation Links */}
          <nav className="flex flex-col gap-1 py-2">
            {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
              const isCurrent = resolveActive(href);
              return (
                <Link
                  key={href}
                  href={href}
                  onClick={onClose}
                  className={cn(
                    "flex items-center gap-3 rounded px-3 py-2 text-sm font-medium transition-colors",
                    isCurrent
                      ? "bg-surface-container-high text-on-surface font-semibold shadow-sm"
                      : "text-on-surface-variant hover:bg-surface-container hover:text-on-surface",
                  )}
                  aria-current={isCurrent ? "page" : undefined}
                >
                  <Icon className="h-4 w-4" />
                  <span>{label}</span>
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Footer info & Logout */}
        <div className="flex flex-col gap-3 pt-3 border-t border-border">
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded bg-surface-container-lowest">
            <span className="h-2 w-2 rounded-full bg-secondary animate-pulse shrink-0" />
            <span className="font-label-mono-sm text-label-mono-sm text-on-surface-variant truncate">
              Pipeline Active · Grounded RAG
            </span>
          </div>

          <div className="flex items-center justify-between p-2 rounded bg-surface-container">
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center font-label-mono-md text-primary shrink-0">
                {initial}
              </div>
              <div className="flex flex-col min-w-0">
                <span className="text-xs font-semibold text-foreground truncate">
                  {name}
                </span>
                <span className="text-[10px] text-muted-foreground truncate">
                  {email || "—"}
                </span>
              </div>
            </div>
            <button
              type="button"
              onClick={() => void handleLogout()}
              className="rounded p-1.5 text-muted-foreground hover:bg-destructive/10 hover:text-destructive transition-colors"
              title="Log out"
              aria-label="Log out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}