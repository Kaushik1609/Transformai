/**
 * KaryaSetu AI — Home / Workspace Route.
 *
 * Unauthenticated users see the public enterprise Landing Page.
 * Authenticated operators see the full KaryaSetu Transformation Workspace.
 */
"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/layout";
import { HomeWorkspace } from "@/components/workspace";
import { LandingPage } from "@/components/landing";
import { isTokenValid, isDevAuthBypassEnabled, getDevSession } from "@/lib/auth";
import { LoadingSpinner } from "@/components/common";

function checkAuth(): "authenticated" | "unauthenticated" {
  if (typeof window === "undefined") return "unauthenticated";
  const authenticated =
    isTokenValid() ||
    (isDevAuthBypassEnabled() && getDevSession() !== null);
  return authenticated ? "authenticated" : "unauthenticated";
}

export default function HomePage() {
  const [authStatus, setAuthStatus] = useState<
    "authenticated" | "unauthenticated"
  >("unauthenticated");

  useEffect(() => {
    setAuthStatus(checkAuth());
  }, []);

  if (authStatus === "unauthenticated") {
    return <LandingPage />;
  }

  return (
    <AppShell active="/">
      <HomeWorkspace />
    </AppShell>
  );
}
