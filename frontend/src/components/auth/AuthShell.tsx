/**
 * TransformIQ — Authentication shell (split-screen).
 *
 * Left: brand + value proposition. Right: the auth form.
 */
"use client";

import Link from "next/link";
import { ReactNode, useState } from "react";
import { LogoMark } from "@/components/brand";
import { Check, Eye, EyeOff } from "lucide-react";

const OUTPUTS = [
  "Summary",
  "LinkedIn",
  "Advisory",
  "Presentation",
  "X Thread",
  "Infographic",
  "Video Package",
];

export function AuthShell({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12 sm:px-6 lg:px-8">
      {/* Background ambient lighting */}
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 left-1/2 h-[450px] w-[550px] -translate-x-1/2 rounded-full bg-primary/10 blur-[120px]" />
        <div className="absolute -bottom-40 left-1/2 h-[450px] w-[550px] -translate-x-1/2 rounded-full bg-accent/10 blur-[120px]" />
      </div>

      <div className="relative z-10 w-full max-w-md space-y-6">
        {/* Brand Header */}
        <div className="text-center">
          <Link
            href="/"
            className="inline-flex items-center gap-2.5 transition-transform hover:scale-105"
          >
            <LogoMark size={38} />
            <span className="text-xl font-bold tracking-tight text-foreground">
              KaryaSetu AI
            </span>
          </Link>
          <p className="mt-1.5 text-xs font-medium uppercase tracking-widest text-muted-foreground">
            One source · Every format
          </p>
        </div>

        {/* Centered Auth Card */}
        <div className="rounded-2xl border border-border/70 bg-card/60 p-6 shadow-2xl backdrop-blur-xl sm:p-8">
          {children}
        </div>

        {/* Footer info */}
        <p className="text-center text-xs text-muted-foreground">
          SIH 26154 — Gen AI Platform for Automated Content Transformation
        </p>
      </div>
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
