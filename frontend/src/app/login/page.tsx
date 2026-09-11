/**
 * TransformIQ — Login page.
 *
 * Phase 15 flow: sign in with email + password. The backend issues a
 * short-lived JWT (POST /api/v1/auth/login) that is stored with setAuthToken().
 * A single generic 401 ("Invalid email or password.") is surfaced for every
 * credential failure — account existence and activation state are not revealed.
 *
 * Development bypass: only when the frontend build explicitly enables it
 * (NEXT_PUBLIC_DEV_AUTH_BYPASS=true) does signing in fall back to a local
 * development identity. It is never the default path.
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
import {
  isDevAuthBypassEnabled,
  setAuthToken,
  setAuthUser,
  setDevSession,
} from "@/lib/auth";
import { authApi, errorMessage } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const devBypass = isDevAuthBypassEnabled();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !password || submitting) {
      setError("Please enter your email and password.");
      return;
    }
    if (devBypass) {
      // Explicitly enabled development path — records a local identity only.
      setSubmitting(true);
      setError(null);
      try {
        await new Promise((r) => setTimeout(r, 350));
        setDevSession(email.trim());
        router.replace("/");
      } catch {
        setError("We couldn't sign you in. Please try again.");
        setSubmitting(false);
      }
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await authApi.login({
        email: email.trim(),
        password,
      });
      setAuthToken(result.access_token, Date.now() + result.expires_in * 1000);
      setAuthUser(result.user);
      router.replace("/");
    } catch (err) {
      setError(errorMessage(err, "We couldn't sign you in. Please try again."));
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
            Sign in to continue to KaryaSetu AI.
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

          <div className="flex justify-end">
            <Link
              href="/forgot-password"
              className="text-sm text-primary hover:underline"
            >
              Forgot password?
            </Link>
          </div>

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit submitting={submitting} label="Sign in" />

          <p className="text-center text-xs text-muted-foreground">
            {devBypass
              ? "Development mode enabled (NEXT_PUBLIC_DEV_AUTH_BYPASS=true)."
              : "Sign in with the password you created when registering."}
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