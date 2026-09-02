/**
 * History page tests.
 *
 * Verifies loading all transformations across projects, the empty state, and
 * the quick-project "Quick Transformation" labeling.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HistoryPage from "@/app/history/page";
import { jsonResponse, type FetchMock } from "./helpers";
import { setDevSession } from "@/lib/auth";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

jest.mock("next/navigation", () => ({
  usePathname: () => "/history",
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

const quickProject = {
  id: "q1",
  user_id: "00000000-0000-0000-0000-000000000001",
  name: "Quick Transformations",
  description: null,
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

const job = {
  id: "j1",
  project_id: "q1",
  source_id: "s1",
  configuration_id: "c1",
  requested_outputs: { output_types: ["summary", "linkedin"] },
  status: "completed",
  progress: 100,
  error_message: null,
  started_at: "2025-01-01T00:00:00Z",
  completed_at: "2025-01-01T00:00:10Z",
  created_at: "2025-01-01T00:00:00Z",
};

function handler() {
  return async (input: RequestInfo | URL) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");
    if (path === "/api/v1/projects") {
      return jsonResponse({ success: true, data: [quickProject], count: 1 });
    }
    if (path.endsWith("/transformations")) {
      return jsonResponse({ success: true, data: [job], count: 1 });
    }
    if (path.endsWith("/outputs")) {
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    return jsonResponse({ detail: `No route ${path}` }, 404);
  };
}

describe("HistoryPage", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(handler());
    localStorage.clear();
    setDevSession("dev@transformiq.local");
  });

  it("shows an empty state when there are no jobs", async () => {
    mockFetch.mockImplementation(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0].replace("http://localhost:8000", "");
      if (path === "/api/v1/projects") {
        return jsonResponse({ success: true, data: [], count: 0 });
      }
      return jsonResponse({ detail: "no route" }, 404);
    });
    render(<HistoryPage />);
    await waitFor(() =>
      expect(screen.getByText("No transformations yet")).toBeInTheDocument(),
    );
  });

  it("lists transformations across projects with quick labeling", async () => {
    render(<HistoryPage />);
    await waitFor(() =>
      expect(screen.getAllByText("Summary").length).toBeGreaterThan(0),
    );
    expect(screen.getByText("Quick Transformation")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn")).toBeInTheDocument();
  });

  it("shows a friendly error when loading fails", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({ detail: "server error" }, 503),
    );
    render(<HistoryPage />);
    await waitFor(() =>
      expect(screen.getByText("Failed to load history.")).toBeInTheDocument(),
    );
  });
});
