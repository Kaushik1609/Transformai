/**
 * Home workspace tests — the unified ChatGPT-style composer.
 *
 * Covers: booting to the composer under the auto-created quick project, and
 * the run gating (source + prompt + outputs required before Run is enabled).
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HomeWorkspace } from "@/components/workspace/HomeWorkspace";
import { jsonResponse, type FetchMock } from "./helpers";

const QUICK_ID = "99999999-9999-9999-9999-999999999999";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

jest.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

const quickProject = {
  id: QUICK_ID,
  user_id: "00000000-0000-0000-0000-000000000001",
  name: "Quick Transformations",
  description: "Your quick transformations live here.",
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

const readySource = {
  id: "src-1",
  project_id: QUICK_ID,
  original_filename: "demo.txt",
  status: "ready",
  created_at: "2025-01-01T00:00:00Z",
  updated_at: "2025-01-01T00:00:00Z",
};

function handler() {
  return async (input: RequestInfo | URL) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");

    if (path === `/api/v1/projects/${QUICK_ID}`) {
      return jsonResponse({ success: true, data: quickProject });
    }
    if (path === "/api/v1/projects") {
      return jsonResponse({ success: true, data: [quickProject], count: 1 });
    }
    if (path.endsWith("/sources")) {
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    if (path.endsWith("/configurations")) {
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    if (path.endsWith("/transformations")) {
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    return jsonResponse({ detail: `No route ${path}` }, 404);
  };
}

describe("HomeWorkspace", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(handler());
    localStorage.clear();
  });

  it("boots under the quick project and shows the composer", async () => {
    render(<HomeWorkspace />);

    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    expect(
      screen.getByRole("button", { name: "Run Transformation" }),
    ).toBeDisabled();
    expect(screen.getByText(/Add a source to begin transforming/)).toBeInTheDocument();
  });

  it("requires a ready source, a prompt, and outputs to run", async () => {
    render(<HomeWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    const run = () => screen.getByRole("button", { name: "Run Transformation" });

    // No source, no prompt, no outputs → disabled.
    expect(run()).toBeDisabled();

    // Fine-grained: still disabled with only a prompt.
    await userEvent.type(
      screen.getByLabelText("Transformation prompt"),
      "Summarize the quarterly results",
    );
    expect(run()).toBeDisabled();

    // Selecting at least one output should now surface the "add a source" only.
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    expect(run()).toBeDisabled();
    expect(
      screen.getByText(/Add a source to begin transforming/),
    ).toBeInTheDocument();
  });
});
