/**
 * TransformIQ — Project workspace route.
 *
 * Route shell for a single project's transformation workspace.
 */
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { TransformationWorkspace } from "@/components/workspace";
import { AppShell } from "@/components/layout";
import { LoadingSpinner } from "@/components/common";

export default function ProjectWorkspacePage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId;

  return (
    <AppShell active="/projects" title="Project">
      <Link
        href="/projects"
        className="mb-4 inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
      >
        ← Projects
      </Link>
      {projectId ? (
        <TransformationWorkspace projectId={projectId} />
      ) : (
        <div className="py-16">
          <LoadingSpinner size="lg" label="Loading project…" />
        </div>
      )}
    </AppShell>
  );
}
