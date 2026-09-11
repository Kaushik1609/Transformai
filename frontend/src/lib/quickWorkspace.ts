/**
 * TransformIQ — Quick workspace helper.
 *
 * Home lets a user transform content WITHOUT manually creating a project. The
 * backend models every source/config/job under a project, so quick
 * transformations are stored under a dedicated auto-created "Quick
 * Transformations" project. This keeps the quick flow free of a manual
 * "create project" step while reusing the existing backend architecture.
 */
"use client";

import { projectsApi, type ProjectResponse } from "@/lib/api";

const QUICK_PROJECT_KEY = "transformiq.quick_project_id";
const QUICK_PROJECT_NAME = "Quick Transformations";

/** A quick transformation belongs to this project — shown as "Quick" in history. */
export function isQuickProject(projectId: string): boolean {
  return projectId === getCachedQuickProjectId();
}

function getCachedQuickProjectId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(QUICK_PROJECT_KEY);
  } catch {
    return null;
  }
}

function setCachedQuickProjectId(id: string): void {
  try {
    window.localStorage.setItem(QUICK_PROJECT_KEY, id);
  } catch {
    // storage unavailable — non-fatal
  }
}

/**
 * Forget the cached quick project. Called on logout so a different analyst
 * does not inherit the previous user's quick workspace.
 */
export function clearQuickProjectId(): void {
  try {
    window.localStorage.removeItem(QUICK_PROJECT_KEY);
  } catch {
    // storage unavailable — non-fatal
  }
}

/**
 * Ensure the quick project exists, creating it if needed. Returns the project.
 */
export async function ensureQuickProject(): Promise<ProjectResponse> {
  const cached = getCachedQuickProjectId();
  if (cached) {
    try {
      const res = await projectsApi.get(cached);
      return res.data;
    } catch {
      // cached project may have been deleted — fall through and recreate
    }
  }

  // Find an existing quick project by name, else create one.
  const list = await projectsApi.list();
  const existing = list.data.find((p) => p.name === QUICK_PROJECT_NAME);
  if (existing) {
    setCachedQuickProjectId(existing.id);
    return existing;
  }

  const created = await projectsApi.create(
    QUICK_PROJECT_NAME,
    "Your quick transformations live here.",
  );
  setCachedQuickProjectId(created.data.id);
  return created.data;
}

/** True when the given project name is the internal quick project. */
export function isQuickProjectName(name: string): boolean {
  return name === QUICK_PROJECT_NAME;
}
