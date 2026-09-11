/**
 * Create Transformation workflow tests — the Stitch-style 4-stage console.
 *
 * Covers: booting under the quick project, the honest operational-mode banner,
 * stage gating (source/prompt required, outputs required, configuration
 * persisted before dispatch), stepper navigation, output package selection
 * (Select All / Reset), and the Phase 15 flexible-input submission contract.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CreateTransformationWorkflow } from "@/components/workspace/CreateTransformationWorkflow";
import { jsonResponse, type FetchMock } from "./helpers";

const QUICK_ID = "99999999-9999-9999-9999-999999999999";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

jest.mock("next/navigation", () => ({
  usePathname: () => "/create",
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
  source_type: "file",
  original_filename: "demo.txt",
  storage_key: null,
  mime_type: "text/plain",
  file_size: 2048,
  language: "en",
  status: "ready",
  source_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
};

function handler({ withSource = false }: { withSource?: boolean } = {}) {
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
    if (path === "/api/v1/sources/src-1") {
      return jsonResponse({ success: true, data: readySource });
    }
    if (path.endsWith("/sources/text") && method === "POST") {
      return jsonResponse({ success: true, data: readySource });
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
        return jsonResponse({
          success: true,
          data: {
            id: "job-1",
            project_id: QUICK_ID,
            source_id: withSource ? "src-1" : null,
            configuration_id: "cfg-1",
            requested_outputs: { output_types: ["summary"] },
            status: "queued",
            progress: 0,
            error_message: null,
            started_at: null,
            completed_at: null,
            created_at: "2025-01-01T00:00:00Z",
          },
        });
      }
      return jsonResponse({ success: true, data: [], count: 0 });
    }
    return jsonResponse({ detail: `No route ${path}` }, 404);
  };
}

async function travelToStage2(prompt = "Summarize the quarterly results") {
  await userEvent.type(
    screen.getByLabelText("Transformation prompt"),
    prompt,
  );
  await userEvent.click(
    screen.getByRole("button", { name: /Continue to Configuration/ }),
  );
  await waitFor(() =>
    expect(screen.getByText("Tone & Style")).toBeInTheDocument(),
  );
}

async function travelToStage3() {
  await travelToStage2();
  await userEvent.click(
    screen.getByRole("button", { name: /Continue to Output Selection/ }),
  );
  await waitFor(() =>
    expect(screen.getByText("Choose Your Outputs")).toBeInTheDocument(),
  );
}

describe("CreateTransformationWorkflow", () => {
  beforeEach(() => {
    mockFetch.mockReset();
    mockFetch.mockImplementation(handler());
    localStorage.clear();
  });

  it("boots under the quick project with the four-stage console", async () => {
    render(<CreateTransformationWorkflow />);

    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    expect(
      screen.getByRole("list", { name: "Transformation steps" }).children,
    ).toHaveLength(4);

    // Honest mode banner — nothing invented.
    expect(screen.getByText(/Operational Mode · Mode —/)).toBeInTheDocument();
    expect(screen.getByText("Awaiting Input")).toBeInTheDocument();

    // No Run/Transform CTA exists until the workflow's final review step.
    expect(
      screen.queryByRole("button", { name: /Transform/i }),
    ).not.toBeInTheDocument();
  });

  it("updates the operational mode banner when a prompt is entered", async () => {
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    await userEvent.type(
      screen.getByLabelText("Transformation prompt"),
      "Summarize the quarterly results",
    );

    expect(screen.getByText(/Mode B/) ).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText(/Prompt Directive/)).toBeInTheDocument();
  });

  it("blocks stage 2 until there is a prompt or a ready source", async () => {
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    expect(
      screen.getByRole("button", { name: /Continue to Configuration/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Step 2 of 4, Configure" }),
    ).toBeDisabled();

    await travelToStage2();
    expect(screen.getByText("Tone & Style")).toBeInTheDocument();
  });

  it("walks prompt → configure → outputs → review with the payload contract", async () => {
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    await travelToStage3();

    expect(
      screen.getByRole("button", { name: /Review & Ready to Execute/ }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Step 4 of 4, Review & Dispatch" }),
    ).toBeDisabled();

    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    expect(screen.getByText("1 format selected")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Review & Ready to Execute/ }),
    );
    await waitFor(() =>
      expect(screen.getByText("Transformation blueprint")).toBeInTheDocument(),
    );

    // The single Run action — the bottom-of-workflow dispatch — is enabled.
    const dispatch = screen.getByRole("button", {
      name: /Dispatch Transformation/,
    });
    expect(dispatch).toBeEnabled();
    await userEvent.click(dispatch);

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/transformations",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    const createCall = mockFetch.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/transformations") && init?.method === "POST",
    );
    const body = JSON.parse(String(createCall?.[1]?.body));
    expect(body.prompt).toBe("Summarize the quarterly results");
    expect(body.output_types).toEqual(["summary"]);
    expect(body.source_id).toBeUndefined();
    expect(body.configuration_id).toBe("cfg-1");
  });

  it("does not preselect a source and supports a source-only run via raw ingest", async () => {
    mockFetch.mockImplementation(handler({ withSource: true }));
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    // Even with a ready source present, nothing is auto-selected after login.
    expect(screen.getByText(/Mode —/)).toBeInTheDocument();
    expect(screen.queryByText(/Source Corpus Active/)).not.toBeInTheDocument();

    // Attach a source explicitly via Raw Ingest.
    await userEvent.click(screen.getByRole("button", { name: /Raw Ingest/ }));
    await userEvent.type(
      screen.getByLabelText("Raw text source"),
      "Draft intelligence excerpt",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Ingest as Source" }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Source Corpus Active/)).toBeInTheDocument(),
    );
    expect(screen.getByText(/Mode A/)).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", { name: /Continue to Configuration/ }),
    );
    await waitFor(() => expect(screen.getByText("Tone & Style")).toBeInTheDocument());
    await userEvent.click(
      screen.getByRole("button", { name: /Continue to Output Selection/ }),
    );
    await waitFor(() =>
      expect(screen.getByText("Choose Your Outputs")).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /Review & Ready to Execute/ }),
    );
    await waitFor(() =>
      expect(screen.getByText("Transformation blueprint")).toBeInTheDocument(),
    );

    await userEvent.click(
      screen.getByRole("button", { name: /Dispatch Transformation/ }),
    );
    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith(
        "http://localhost:8000/api/v1/transformations",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    const createCall = mockFetch.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/transformations") && init?.method === "POST",
    );
    const body = JSON.parse(String(createCall?.[1]?.body));
    expect(body.source_id).toBe("src-1");
    expect(body.prompt).toBeUndefined();
  });

  it("supports Select All and Reset on the output package grid", async () => {
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    await travelToStage3();

    await userEvent.click(screen.getByRole("button", { name: "Select All" }));
    expect(screen.getByText("7 formats selected")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(screen.getByText("0 formats selected")).toBeInTheDocument();

    expect(
      screen.getByRole("button", { name: /Review & Ready to Execute/ }),
    ).toBeDisabled();
  });

  it("never invents security or pipeline metrics", async () => {
    render(<CreateTransformationWorkflow />);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Create Transformation" }),
      ).toBeInTheDocument(),
    );

    await travelToStage3();
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );

    expect(screen.queryByText(/[\d.]+% safe/)).not.toBeInTheDocument();
    expect(screen.queryByText(/48 pages/)).not.toBeInTheDocument();
    expect(screen.queryByText(/1,420 chunks/)).not.toBeInTheDocument();
    expect(screen.queryByText(/99\.4%/)).not.toBeInTheDocument();
  });
});