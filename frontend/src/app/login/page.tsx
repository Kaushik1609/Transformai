/**
 * TransformIQ — Login page.
 *
 * The backend currently authenticates via a stable development identity
 * (DEV_AUTH_BYPASS). Signing in proceeds to the app without issuing a JWT —
 * no credentials are invented or transmitted.
 */
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  AuthShell,
  PasswordInput,
  AuthSubmit,
} from "@/components/auth";
import { setDevSession } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password || submitting) {
      setError("Please enter your email and password.");
      return;
    }
    setSubmitting(true);
    setError(null);
    // The backend runs with DEV_AUTH_BYPASS — proceed to the app.
    try {
      await new Promise((r) => setTimeout(r, 350));
      setDevSession(email.trim());
      router.replace("/");
    } catch {
      setError("We couldn't sign you in. Please try again.");
      setSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Welcome back
          </h2>
          <p className="text-sm text-muted-foreground">
            Sign in to continue to TransformIQ.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="space-y-1.5">
            <label
              htmlFor="email"
              className="block text-sm font-medium text-foreground"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
              className="input-base"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="password"
              className="block text-sm font-medium text-foreground"
            >
              Password
            </label>
            <PasswordInput
              id="password"
              value={password}
              onChange={setPassword}
              placeholder="Password"
              autoComplete="current-password"
            />
          </div>

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="h-4 w-4 rounded border-input"
              />
              Remember me
            </label>
            <button
              type="button"
              className="text-sm text-primary hover:underline"
            >
              Forgot password?
            </button>
          </div>

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit submitting={submitting} label="Sign in" />

          <p className="text-center text-xs text-muted-foreground">
            This build uses a development identity. Real authentication is not
            yet enabled.
          </p>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Link href="/register" className="font-medium text-primary hover:underline">
            Create account
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}
