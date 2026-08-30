/**
 * TransformIQ — Project workspace route (Phase 9).
 *
 * Route shell for a single project's transformation workspace.
 */
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { TransformationWorkspace } from "@/components/workspace";
import { DashboardLayout } from "@/components/layout";
import { LoadingSpinner } from "@/components/common";

export default function ProjectWorkspacePage() {
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId;

  return (
    <DashboardLayout>
      <div className="mb-4">
        <Link
          href="/projects"
          className="text-xs text-muted-foreground underline underline-offset-2 transition-colors hover:text-foreground"
        >
          ← Back to projects
        </Link>
      </div>
      {projectId ? (
        <TransformationWorkspace projectId={projectId} />
      ) : (
        <div className="py-16">
          <LoadingSpinner size="lg" label="Loading project…" />
        </div>
      )}
    </DashboardLayout>
  );
}