/**
 * UI-7 — Project detail page tests.
 *
 * The route is organized PROJECT → SOURCE LIBRARY → TRANSFORMATIONS &
 * ACTIVITY. These tests pin the header (with honest OWNER-SCOPED framing),
 * the source library wiring, the ?source= preselect and the workspace mount.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectDetailPage from "@/app/projects/[projectId]/page";
import { setDevSession } from "@/lib/auth";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

let mockSearchParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "p1" }),
  useSearchParams: () => mockSearchParams,
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  usePathname: () => "/projects/p1",
}));

const projectPayload = {
  success: true,
  data: {
    id: "p1",
    user_id: "user-1",
    name: "Alpha Deal",
    description: "M&A analysis",
    created_at: "2025-01-01T00:00:00Z",
    updated_at: "2025-01-02T00:00:00Z",
  },
};

const sourcePayload = {
  success: true,
  data: [
    {
      id: "alpha",
      project_id: "p1",
      source_type: "file",
      original_filename: "Alpha.pdf",
      storage_key: "k-alpha",
      mime_type: "application/pdf",
      file_size: 20480,
      language: "en",
      status: "ready",
      source_metadata: {
        malware_scan: { status: "clean", scanner: "clamav" },
        pii_scan: { detected: false, counts: {} },
      },
      created_at: "2025-01-01T00:00:00Z",
    },
  ],
  count: 1,
};

const emptyList = { success: true, data: [], count: 0 };

function handlerWithSources(sourcesData: unknown) {
  return async (input: RequestInfo | URL) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");

    if (/^\/api\/v1\/projects\/[^/]+\/sources$/.test(path)) {
      return jsonResponse(sourcesData);
    }
    if (/^\/api\/v1\/projects\/[^/]+\/configurations$/.test(path)) {
      return jsonResponse(emptyList);
    }
    if (/^\/api\/v1\/projects\/[^/]+\/transformations$/.test(path)) {
      return jsonResponse(emptyList);
    }
    if (/^\/api\/v1\/projects\/[^/]+$/.test(path)) {
      return jsonResponse(projectPayload);
    }
    return jsonResponse(emptyList);
  };
}

const defaultHandler = () => handlerWithSources(sourcePayload);

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockImplementation(defaultHandler());
  mockSearchParams = new URLSearchParams();
  localStorage.clear();
  setDevSession("dev@transformiq.local");
  process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
});

describe("ProjectDetailPage — project header", () => {
  it("shows the project header, description and owner-scoped framing", async () => {
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("Alpha Deal")).toBeInTheDocument(),
    );
    expect(screen.getByText("M&A analysis")).toBeInTheDocument();
    expect(screen.getByText("OWNER-SCOPED")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "← Projects" }),
    ).toHaveAttribute("href", "/projects");
  });

  it("shows a friendly error and retries the project load", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({ detail: "boom" }, 503),
    );
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Failed to load this project."),
      ).toBeInTheDocument(),
    );

    mockFetch.mockImplementation(defaultHandler());
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(
        within(
          screen.getByRole("region", { name: /^project$/i }),
        ).getByText("Alpha Deal"),
      ).toBeInTheDocument(),
    );
  });
});

describe("ProjectDetailPage — source library", () => {
  it("shows the source library section with source status", async () => {
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: /source library/i }),
      ).toBeInTheDocument(),
    );
    const library = screen.getByRole("region", { name: /source library/i });
    await waitFor(() =>
      expect(within(library).getByText("Alpha.pdf")).toBeInTheDocument(),
    );
    expect(within(library).getByText("Malware CLEAN")).toBeInTheDocument();
  });

  it("selects a source and moves the workspace onto it via Transform", async () => {
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: /source library/i }),
      ).toBeInTheDocument(),
    );
    const library = screen.getByRole("region", { name: /source library/i });
    await waitFor(() =>
      expect(within(library).getByText("Alpha.pdf")).toBeInTheDocument(),
    );
    const transform = within(library).getByRole("button", {
      name: "Transform with this source",
    });
    expect(transform).not.toHaveAttribute("aria-pressed", "true");

    await userEvent.click(transform);
    expect(within(library).getByText("Selected")).toBeInTheDocument();
    expect(
      within(library).getByRole("button", {
        name: "Transform with this source",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("honors the ?source= preselect from the URL", async () => {
    mockSearchParams = new URLSearchParams("source=alpha");
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: /source library/i }),
      ).toBeInTheDocument(),
    );
    const library = screen.getByRole("region", { name: /source library/i });
    await waitFor(() =>
      expect(within(library).getByText("Alpha.pdf")).toBeInTheDocument(),
    );
    expect(within(library).getByText("Selected")).toBeInTheDocument();
    expect(
      within(library).getByRole("button", {
        name: "Transform with this source",
      }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("shows an empty library when the project has no sources", async () => {
    mockFetch.mockImplementation(handlerWithSources(emptyList));
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByRole("region", { name: /source library/i }),
      ).toBeInTheDocument(),
    );
    const library = screen.getByRole("region", { name: /source library/i });
    await waitFor(() =>
      expect(within(library).getByText("No sources yet")).toBeInTheDocument(),
    );
  });
});

describe("ProjectDetailPage — transformations & activity", () => {
  it("mounts the transformation workspace under the section heading", async () => {
    render(<ProjectDetailPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Transformations & activity"),
      ).toBeInTheDocument(),
    );
    // The workspace boots and renders its setup column.
    await waitFor(() =>
      expect(screen.getByText("1 · Source")).toBeInTheDocument(),
    );
  });
});