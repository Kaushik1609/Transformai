/**
 * TransformIQ — Forgot password page.
 *
 * Phase 15: request a password-reset code. The response is intentionally
 * generic — the backend does not disclose whether an email is registered.
 */
"use client";

import { useState } from "react";
import Link from "next/link";
import { AuthShell, AuthSubmit } from "@/components/auth";
import { authApi, errorMessage } from "@/lib/api";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || submitting) {
      setError("Please enter your account email.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await authApi.forgotPassword({ email: email.trim() });
      setSent(true);
    } catch (err) {
      setError(
        errorMessage(err, "We couldn't start a password reset. Please try again."),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {sent ? "Check your email" : "Reset your password"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {sent
              ? "If an account exists for that email, we've sent a verification code to reset your password."
              : "Enter your account email and we'll send you a one-time code."}
          </p>
        </div>

        {sent ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Open the email and use the code on the{" "}
              <Link
                href={`/reset-password?email=${encodeURIComponent(email)}`}
                className="font-medium text-primary hover:underline"
              >
                reset password
              </Link>{" "}
              page.
            </p>
            <p className="text-center text-sm text-muted-foreground">
              <Link href="/login" className="font-medium text-primary hover:underline">
                Back to sign in
              </Link>
            </p>
          </div>
        ) : (
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

            {error && (
              <p role="alert" className="text-xs font-medium text-destructive">
                {error}
              </p>
            )}

            <AuthSubmit submitting={submitting} label="Send reset code" />

            <p className="text-center text-sm text-muted-foreground">
              Remembered it?{" "}
              <Link href="/login" className="font-medium text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </form>
        )}
      </div>
    </AuthShell>
  );
}