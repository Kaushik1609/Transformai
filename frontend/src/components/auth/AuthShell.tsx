/**
 * TransformIQ — Authentication shell (split-screen).
 *
 * Left: brand + value proposition. Right: the auth form.
 */
"use client";

import Link from "next/link";
import { ReactNode, useState } from "react";
import { LogoMark } from "@/components/brand";
import { Eye, EyeOff } from "lucide-react";
import { WorkflowGraphAnimation } from "@/components/demo/WorkflowGraphAnimation";

export function AuthShell({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background">
      {/* Left — 50% window space: enterprise brand and architecture animation */}
      <div className="relative hidden w-1/2 min-h-screen max-h-screen flex-col justify-between overflow-hidden border-r border-border bg-card text-foreground transition-colors duration-200 p-6 lg:flex lg:p-8">
        {/* Top: Branding & clean headline */}
        <div className="mb-3 shrink-0 space-y-1.5">
          <Link href="/" className="flex items-center gap-2.5">
            <LogoMark size={32} />
            <span className="text-lg font-semibold tracking-tight text-foreground">
              KaryaSetu AI
            </span>
          </Link>
          <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-foreground">
            End-to-End Governed AI Pipeline
          </h1>
        </div>

        {/* Down: Full workflow architecture animation */}
        <div className="relative flex-1 w-full min-h-0 flex items-center justify-center overflow-hidden rounded-lg border border-border bg-surface-container-lowest shadow-xs transition-colors">
          <WorkflowGraphAnimation authMode={true} />
        </div>
      </div>

      {/* Right — 50% window space for auth form */}
      <main className="flex w-full flex-1 lg:w-1/2 min-h-screen items-center justify-center p-6 bg-muted/20 dark:bg-background">
        <div className="w-full max-w-sm rounded-xl border border-border/80 bg-card p-6 sm:p-7 shadow-xs">
          {children}
        </div>
      </main>
    </div>
  );
}


export function PasswordInput({
  value,
  onChange,
  id,
  placeholder,
  autoComplete,
}: {
  value: string;
  onChange: (v: string) => void;
  id: string;
  placeholder?: string;
  autoComplete?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative">
      <input
        id={id}
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Password"}
        autoComplete={autoComplete ?? "current-password"}
        className="input-base pr-10"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground transition-colors hover:text-foreground"
        aria-label={show ? "Hide password" : "Show password"}
      >
        {show ? (
          <EyeOff className="h-4 w-4" aria-hidden="true" />
        ) : (
          <Eye className="h-4 w-4" aria-hidden="true" />
        )}
      </button>
    </div>
  );
}

export function AuthSubmit({
  submitting,
  label,
}: {
  submitting: boolean;
  label: string;
}) {
  return (
    <button
      type="submit"
      disabled={submitting}
      className="inline-flex w-full items-center justify-center rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {submitting ? "Please wait…" : label}
    </button>
  );
}
