/**
 * TransformIQ — Application authentication gate.
 *
 * Grants access when either:
 *   1. The frontend build explicitly enables the development bypass
 *      (NEXT_PUBLIC_DEV_AUTH_BYPASS=true) AND a development session exists.
 *   2. A stored access token is present and has not expired.
 *
 * When a token exists but is expired it is removed so stale credentials never
 * linger in storage. Otherwise the user is redirected to /login.
 */
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import {
  clearAuthToken,
  getAuthToken,
  getDevSession,
  isDevAuthBypassEnabled,
  isTokenValid,
} from "@/lib/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const validToken = isTokenValid();

    // An expired/invalid token must never sit in storage.
    if (!validToken && getAuthToken() !== null) {
      clearAuthToken();
    }

    const devBypass = isDevAuthBypassEnabled() && getDevSession() !== null;

    if (validToken || devBypass) {
      setReady(true);
      return;
    }

    router.replace("/login");
  }, [router]);

  return <>{ready ? children : null}</>;
}