/**
 * TransformIQ — Application Header / Navigation
 *
 * Top navigation bar containing the brand identity and phase indicator.
 */
import Link from "next/link";
import { cn } from "@/lib/utils";

interface HeaderProps {
  className?: string;
}

export function Header({ className }: HeaderProps) {
  return (
    <header
      className={cn(
        "sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60",
        className,
      )}
    >
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4 sm:px-6">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-lg font-bold tracking-tight text-foreground"
          >
            TransformIQ
          </Link>
          <span className="hidden rounded-full border border-border bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground sm:inline-flex">
            Beta
          </span>
        </div>

        {/* Nav links */}
        <nav
          aria-label="Main navigation"
          className="hidden items-center gap-6 sm:flex"
        >
          <NavLink href="/" label="Home" />
          <NavLink href="/projects" label="Projects" active />
        </nav>

        {/* Right side — dev identity badge */}
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-border bg-muted px-3 py-1 text-xs text-muted-foreground">
            SIH 26154
          </span>
        </div>
      </div>
    </header>
  );
}

// ---------------------------------------------------------------------------
// Internal sub-component
// ---------------------------------------------------------------------------

interface NavLinkProps {
  href: string;
  label: string;
  active?: boolean;
}

function NavLink({ href, label, active }: NavLinkProps) {
  return (
    <Link
      href={href}
      className={cn(
        "text-sm transition-colors hover:text-foreground",
        active ? "font-medium text-foreground" : "text-muted-foreground",
      )}
    >
      {label}
    </Link>
  );
}
