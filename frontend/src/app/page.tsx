/**
 * TransformIQ — Home page.
 *
 * The primary AI transformation workspace. Users describe what they want,
 * upload a source once, set tone/audience, select multiple outputs, and run a
 * single orchestrated transformation.
 */
"use client";

import { AppShell } from "@/components/layout";
import { HomeWorkspace } from "@/components/workspace";

export default function HomePage() {
  return (
    <AppShell active="/">
      <HomeWorkspace />
    </AppShell>
  );
}
