/**
 * Quick Workspace helper tests.
 *
 * Verifies the auto-managed "Quick Transformations" project strategy:
 * caching, find-by-name before create, and helper predicates.
 */
import {
  ensureQuickProject,
  isQuickProject,
  isQuickProjectName,
} from "@/lib/quickWorkspace";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const QUICK_ID = "88888888-8888-8888-8888-888888888888";

const quickProject = {
  id: QUICK_ID,
  user_id: "00000000-0000-0000-0000-000000000001",
  name: "Quick Transformations",
  description: "Your quick transformations live here.",
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

describe("quickWorkspace", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
  });

  it("creates the quick project when none exists", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: [], count: 0 })) // list → none
      .mockResolvedValueOnce(jsonResponse({ success: true, data: quickProject }, 201)); // create

    const project = await ensureQuickProject();
    expect(project.id).toBe(QUICK_ID);
    expect(isQuickProject(QUICK_ID)).toBe(true);
    expect(isQuickProjectName(project.name)).toBe(true);
    expect(localStorage.getItem("transformiq.quick_project_id")).toBe(QUICK_ID);
  });

  it("reuses an existing quick project by name without creating", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: [quickProject], count: 1 }),
    );

    const project = await ensureQuickProject();
    expect(project.id).toBe(QUICK_ID);
    // No POST create call should have occurred.
    expect(
      mockFetch.mock.calls.some(
        (c) => String(c[0]).endsWith("/api/v1/projects") && c[1]?.method === "POST",
      ),
    ).toBe(false);
  });
});
