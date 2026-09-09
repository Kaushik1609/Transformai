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
    <div className="flex min-h-screen bg-background">
      {/* Left — brand panel */}
      <div className="relative hidden w-1/2 flex-col justify-between overflow-hidden border-r border-border bg-surface-elevated p-10 lg:flex">
        <Link href="/" className="flex items-center gap-2.5">
          <LogoMark size={34} />
          <span className="text-lg font-semibold tracking-tight text-foreground">
            TransformIQ
          </span>
        </Link>

        <div className="space-y-6">
          <div className="space-y-2">
            <h1 className="text-4xl font-bold leading-tight tracking-tight text-foreground">
              One source.
              <br />
              Every format.
            </h1>
            <p className="max-w-md text-muted-foreground">
              Upload your source, describe what you need, choose your outputs,
              and let TransformIQ orchestrate the rest.
            </p>
          </div>

          <ul className="grid max-w-md grid-cols-2 gap-2">
            {OUTPUTS.map((o) => (
              <li
                key={o}
                className="flex items-center gap-2 text-sm text-muted-foreground"
              >
                <Check className="h-4 w-4 text-primary" aria-hidden="true" />
                {o}
              </li>
            ))}
          </ul>
        </div>

        <p className="text-xs text-muted-foreground">
          7 output formats · 1 prompt or source
        </p>
      </div>

      {/* Right — form panel */}
      <div className="flex w-full flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm">{children}</div>
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
