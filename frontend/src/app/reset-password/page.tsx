/**
 * TransformIQ — Reset password page.
 *
 * Phase 15: confirm the one-time code received by email and set a new
 * password. The backend replaces the stored PBKDF2 hash on success.
 */
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AuthShell, PasswordInput, AuthSubmit } from "@/components/auth";
import { authApi, errorMessage } from "@/lib/api";

function isValidCode(code: string): boolean {
  return /^\d{6,12}$/.test(code.trim());
}

export default function ResetPasswordPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const emailParam = params.get("email");
      const codeParam = params.get("code");
      if (emailParam) setEmail(emailParam);
      if (codeParam) setCode(codeParam);
    }
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !isValidCode(code)) {
      setError("Please enter your email and the 6-digit verification code.");
      return;
    }
    if (!newPassword || newPassword.length < 8) {
      setError("Your new password must be at least 8 characters long.");
      return;
    }
    if (newPassword !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await authApi.resetPassword({
        email: email.trim(),
        otp: code.trim(),
        new_password: newPassword,
      });
      setDone(true);
    } catch (err) {
      setError(
        errorMessage(err, "We couldn't reset your password. Please try again."),
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (done) {
    return (
      <AuthShell>
        <div className="space-y-6">
          <div className="space-y-1">
            <h2 className="text-2xl font-semibold tracking-tight text-foreground">
              Password updated
            </h2>
            <p className="text-sm text-muted-foreground">
              Your password has been changed. Sign in with your new password.
            </p>
          </div>
          <button
            type="button"
            onClick={() => router.replace("/login")}
            className="inline-flex w-full items-center justify-center rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Sign in
          </button>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Set a new password
          </h2>
          <p className="text-sm text-muted-foreground">
            Enter the code you received by email, then choose a new password.
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
              htmlFor="code"
              className="block text-sm font-medium text-foreground"
            >
              Verification code
            </label>
            <input
              id="code"
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="6-digit code"
              className="input-base"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="new-password"
              className="block text-sm font-medium text-foreground"
            >
              New password
            </label>
            <PasswordInput
              id="new-password"
              value={newPassword}
              onChange={setNewPassword}
              placeholder="New password"
              autoComplete="new-password"
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="confirm"
              className="block text-sm font-medium text-foreground"
            >
              Confirm new password
            </label>
            <PasswordInput
              id="confirm"
              value={confirm}
              onChange={setConfirm}
              placeholder="Confirm new password"
              autoComplete="new-password"
            />
          </div>

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit submitting={submitting} label="Reset password" />

          <p className="text-center text-sm text-muted-foreground">
            Need a new code?{" "}
            <Link href="/forgot-password" className="font-medium text-primary hover:underline">
              Request another
            </Link>
          </p>
        </form>
      </div>
    </AuthShell>
  );
}