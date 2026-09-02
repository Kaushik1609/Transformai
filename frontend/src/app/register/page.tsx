/**
 * TransformIQ — Register page.
 *
 * The backend currently authenticates via a stable development identity
 * (DEV_AUTH_BYPASS). Registration proceeds to the app without persisting fake
 * user records.
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

export default function RegisterPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  };

  return (
    <AuthShell>
      <div className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Create your account
          </h2>
          <p className="text-sm text-muted-foreground">
            Start transforming one source into many formats.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
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

          {error && (
            <p role="alert" className="text-xs font-medium text-destructive">
              {error}
            </p>
          )}

          <AuthSubmit submitting={submitting} label="Create account" />

          <p className="text-center text-xs text-muted-foreground">
            This build uses a development identity. Real authentication is not
            yet enabled.
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
