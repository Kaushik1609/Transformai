/**
 * TransformIQ — Register page.
 *
 * Phase 15 flow: register with a password (creates the account as INACTIVE and
 * issues a verification OTP), then exchange the code for a short-lived access
 * token via POST /api/v1/auth/verify. Verifying activates the account.
 *
 * Development bypass: only when the frontend build explicitly enables it
 * (NEXT_PUBLIC_DEV_AUTH_BYPASS=true) does registration proceed with a local
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

function isValidCode(code: string): boolean {
  return /^\d{6,12}$/.test(code.trim());
}

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [step, setStep] = useState<"details" | "otp">("details");
  const [otp, setOtp] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resent, setResent] = useState(false);

  const devBypass = isDevAuthBypassEnabled();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !email.trim() || !password) {
      setError("Please fill in all fields.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    if (devBypass) {
      // Explicitly enabled development path — records a local identity only.
      setSubmitting(true);
      setError(null);
      try {
        await new Promise((r) => setTimeout(r, 350));
        setDevSession(email.trim(), name.trim());
        router.replace("/");
      } catch {
        setError("We couldn't create your account. Please try again.");
        setSubmitting(false);
      }
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await authApi.register({
        name: name.trim(),
        email: email.trim(),
        password,
      });
      setStep("otp");
    } catch (err) {
      setError(
        errorMessage(err, "We couldn't send the verification email. Please try again later."),
      );
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
      setAuthUser(result.user);
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

  const handleResend = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      await authApi.resendOtp({ email: email.trim() });
      setResent(true);
    } catch (err) {
      setError(
        errorMessage(err, "We couldn't send a new code. Please try again."),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const backToDetails = () => {
    setStep("details");
    setOtp("");
    setError(null);
  };

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            {step === "otp" ? "Check your email" : "Create your account"}
          </h2>
          <p className="text-sm text-muted-foreground">
            {step === "otp"
              ? `Enter the one-time code sent to ${email.trim()}.`
              : "Start transforming one source into many formats."}
          </p>
        </div>

        <form
          onSubmit={step === "otp" ? handleVerify : handleSubmit}
          className="space-y-4"
        >
          {step === "details" ? (
            <>
              <div className="space-y-1.5">
                <label
                  htmlFor="name"
                  className="block text-sm font-medium text-foreground"
                >
                  Name
                </label>
                <input
                  id="name"
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Your name"
                  autoComplete="name"
                  className="input-base"
                />
              </div>

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
                  autoComplete="new-password"
                />
              </div>

              <div className="space-y-1.5">
                <label
                  htmlFor="confirm"
                  className="block text-sm font-medium text-foreground"
                >
                  Confirm password
                </label>
                <PasswordInput
                  id="confirm"
                  value={confirm}
                  onChange={setConfirm}
                  placeholder="Confirm password"
                  autoComplete="new-password"
                />
              </div>

              <p className="text-xs text-muted-foreground">
                Use 8–128 characters. Your password is stored only as a
                cryptographic hash.
              </p>
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

              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={handleResend}
                  disabled={submitting}
                  className="text-sm text-primary hover:underline disabled:opacity-60"
                >
                  Resend code
                </button>
                <button
                  type="button"
                  onClick={backToDetails}
                  className="text-sm text-muted-foreground hover:text-foreground"
                >
                  Use a different email
                </button>
              </div>

              {resent && (
                <p className="text-xs font-medium text-muted-foreground">
                  A new code has been sent.
                </p>
              )}
            </>
          )}

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit
            submitting={submitting}
            label={step === "otp" ? "Verify code" : "Create account"}
          />

          <p className="text-center text-xs text-muted-foreground">
            {devBypass
              ? "Development mode enabled (NEXT_PUBLIC_DEV_AUTH_BYPASS=true)."
              : "Registration sends a one-time verification code to your email."}
          </p>
        </form>

        <p className="text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </div>
    </AuthShell>
  );
}