/**
 * TransformIQ — Development-session gate.
 *
 * Protects the application shell. Until a development session is present the
 * shell renders nothing and the user is redirected to /login. Rendering stays
 * empty for the first (server) pass so there is no hydration mismatch.
 */
"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getDevSession } from "@/lib/auth";

export function RequireAuth({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getDevSession()) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  return <>{ready ? children : null}</>;
}