/**
 * TransformIQ — Login page.
 *
 * Primary flow (Phase 11F): request an OTP for the account email, then
 * exchange it for a short-lived access token via POST /api/v1/auth/verify.
 * On success the JWT and its expiry are stored with setAuthToken().
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
  setDevSession,
} from "@/lib/auth";
import { authApi, errorMessage } from "@/lib/api";

function isValidCode(code: string): boolean {
  return /^\d{6,12}$/.test(code.trim());
}

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [step, setStep] = useState<"credentials" | "otp">("credentials");
  const [otp, setOtp] = useState("");
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
      await authApi.login({ email: email.trim() });
      setStep("otp");
    } catch (err) {
      setError(errorMessage(err, "We couldn't start the sign-in. Please try again."));
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidCode(otp) || submitting) {
      setError("Please enter the 6-digit verification code.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await authApi.verifyOtp({ email: email.trim(), otp: otp.trim() });
      setAuthToken(result.access_token, Date.now() + result.expires_in * 1000);
      router.replace("/");
    } catch (err) {
      setError(
        errorMessage(
          err,
          "The verification code is incorrect or has expired. Please try again.",
        ),
      );
      setSubmitting(false);
    }
  };

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {step === "otp" ? "Check your email" : "Welcome back"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {step === "otp"
              ? `Enter the one-time code sent to ${email.trim()}.`
              : "Sign in to continue to TransformIQ."}
          </p>
        </div>

        <form
          onSubmit={step === "otp" ? handleVerify : handleSubmit}
          className="space-y-4"
        >
          {step === "credentials" ? (
            <>
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
            </>
          ) : (
            <>
              <div className="space-y-1.5">
                <label
                  htmlFor="otp"
                  className="block text-sm font-medium text-foreground"
                >
                  Verification code
                </label>
                <input
                  id="otp"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={otp}
                  onChange={(e) => setOtp(e.target.value)}
                  placeholder="6-digit code"
                  className="input-base"
                />
              </div>

              <button
                type="button"
                onClick={() => {
                  setStep("credentials");
                  setOtp("");
                  setError(null);
                }}
                className="text-sm text-muted-foreground hover:text-foreground"
              >
                Use a different email
              </button>
            </>
          )}

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit
            submitting={submitting}
            label={step === "otp" ? "Verify code" : "Sign in"}
          />

          <p className="text-center text-xs text-muted-foreground">
            {devBypass
              ? "Development mode enabled (NEXT_PUBLIC_DEV_AUTH_BYPASS=true)."
              : "Signing in sends a one-time verification code to your email."}
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