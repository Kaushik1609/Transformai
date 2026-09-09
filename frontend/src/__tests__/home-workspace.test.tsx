/**
 * Home workspace tests — the unified ChatGPT-style composer.
 *
 * Covers: booting to the composer under the auto-created quick project, and
 * the Phase 15 flexible-input gating — prompt-only, source-only, or both are
 * valid before Run is enabled.
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

const job = {
  id: "job-1",
  project_id: QUICK_ID,
  source_id: "src-1",
  configuration_id: "cfg-1",
  requested_outputs: { output_types: ["summary"] },
  status: "queued",
  progress: 0,
  error_message: null,
  started_at: null,
  completed_at: null,
  created_at: "2025-01-01T00:00:00Z",
};

function handler({
  withSource = false,
}: { withSource?: boolean } = {}) {
  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");
    const method = init?.method ?? "GET";

    if (path === `/api/v1/projects/${QUICK_ID}`) {
      return jsonResponse({ success: true, data: quickProject });
    }
    if (path === "/api/v1/projects") {
      return jsonResponse({ success: true, data: [quickProject], count: 1 });
    }
    if (path.endsWith("/sources")) {
      return jsonResponse({
        success: true,
        data: withSource ? [readySource] : [],
        count: withSource ? 1 : 0,
      });
    }
    if (path.endsWith("/configurations")) {
      if (method === "POST") {
        return jsonResponse({
          success: true,
          data: {
            id: "cfg-1",
            project_id: QUICK_ID,
            target_audience: null,
            tone: null,
            language: "English",
            detail_level: "standard",
            created_at: "2025-01-01T00:00:00Z",
          },
        });
      }
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    if (path.endsWith("/transformations")) {
      if (method === "POST") {
        return jsonResponse({ success: true, data: job });
      }
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
      screen.getByRole("button", { name: "Transform" }),
    ).toBeDisabled();
    expect(
      screen.getByText(/Describe what to create and\/or attach a source/),
    ).toBeInTheDocument();
  });

  it("allows a prompt-only run (no source attached)", async () => {
    mockFetch.mockImplementation(handler());
    render(<HomeWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    const run = () => screen.getByRole("button", { name: "Transform" });
    expect(run()).toBeDisabled();

    await userEvent.type(
      screen.getByLabelText("Transformation prompt"),
      "Summarize the quarterly results",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    expect(run()).toBeEnabled();
    expect(
      screen.getByText(/your instruction \(no source attached\)/),
    ).toBeInTheDocument();
  });

  it("sends the prompt-only payload (no source_id) when running without a source", async () => {
    mockFetch.mockImplementation(handler());
    render(<HomeWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    await userEvent.type(
      screen.getByLabelText("Transformation prompt"),
      "Summarize the quarterly results",
    );
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Transform" }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/transformations",
        expect.objectContaining({
          method: "POST",
          body: expect.stringContaining('"prompt":"Summarize the quarterly results"'),
        }),
      ),
    );
    const createCall = mockFetch.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/transformations") && init?.method === "POST",
    );
    const body = JSON.parse(String(createCall?.[1]?.body));
    expect(body.prompt).toBe("Summarize the quarterly results");
    expect(body.source_id).toBeUndefined();

    // The config persisted by the run carries the selected output language.
    const configCall = mockFetch.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith(`/projects/${QUICK_ID}/configurations`) &&
        init?.method === "POST",
    );
    const configBody = JSON.parse(String(configCall?.[1]?.body));
    expect(configBody.language).toBe("English");
  });

  it("allows a source-only run (ready source, no prompt)", async () => {
    mockFetch.mockImplementation(handler({ withSource: true }));
    render(<HomeWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );

    const run = () => screen.getByRole("button", { name: "Transform" });
    expect(run()).toBeEnabled();
    expect(
      screen.getByText(/your source \(no additional instruction\)/),
    ).toBeInTheDocument();
  });

  it("still requires outputs to run", async () => {
    render(<HomeWorkspace />);
    await waitFor(() =>
      expect(
        screen.getByText("What would you like to transform?"),
      ).toBeInTheDocument(),
    );

    const run = () => screen.getByRole("button", { name: "Transform" });
    await userEvent.type(
      screen.getByLabelText("Transformation prompt"),
      "Summarize the quarterly results",
    );
    expect(run()).toBeDisabled();
    expect(
      screen.getByText(/Choose one or more output formats to get started/),
    ).toBeInTheDocument();
  });
});