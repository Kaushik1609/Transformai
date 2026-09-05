/**
 * Phase 9 tests — Projects page (create / list / select).
 *
 * Covers project listing, creation via the modal (empty → opens modal →
 * create), empty and error states, and navigation links into a project
 * workspace.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectsPage from "@/app/projects/page";
import { jsonResponse, type FetchMock } from "./helpers";
import { setDevSession } from "@/lib/auth";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
  usePathname: () => "/projects",
}));

beforeEach(() => {
  mockFetch.mockReset();
  // Default for the project list + per-project stats fetches.
  mockFetch.mockResolvedValue(
    jsonResponse({ success: true, data: [], count: 0 }),
  );
  localStorage.clear();
  process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
  setDevSession("dev@transformiq.local");
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
});

const projectsPayload = {
  success: true,
  data: [
    {
      id: "p1",
      name: "Alpha Deal",
      description: "M&A analysis",
      created_at: "2025-01-01T00:00:00Z",
      updated_at: "2025-01-01T00:00:00Z",
    },
    {
      id: "p2",
      name: "Quarterly Review",
      description: null,
      created_at: "2025-01-02T00:00:00Z",
      updated_at: "2025-01-02T00:00:00Z",
    },
  ],
  count: 2,
};

describe("ProjectsPage", () => {
  it("shows loading, then lists projects with links", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(projectsPayload));
    render(<ProjectsPage />);

    await waitFor(() =>
      expect(screen.getAllByText("Loading projects…").length).toBeGreaterThan(0),
    );

    await waitFor(() => expect(screen.getByText("Alpha Deal")).toBeInTheDocument());
    expect(screen.getByText("M&A analysis")).toBeInTheDocument();
    expect(screen.getByText("Quarterly Review")).toBeInTheDocument();

    const alpha = screen.getByText("Alpha Deal").closest("a");
    expect(alpha).toHaveAttribute("href", "/projects/p1");
  });

  it("shows an empty state when the user has no projects", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: [], count: 0 }));
    render(<ProjectsPage />);

    await waitFor(() =>
      expect(screen.getByText("No projects yet")).toBeInTheDocument(),
    );
  });

  it("shows a friendly error when loading fails", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Internal Server Error" }, 503),
    );
    render(<ProjectsPage />);

    await waitFor(() =>
      expect(screen.getByText("Failed to load projects.")).toBeInTheDocument(),
    );

    mockFetch.mockResolvedValueOnce(jsonResponse(projectsPayload));
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("Alpha Deal")).toBeInTheDocument());
  });

  it("creates a project via the modal and posts the correct payload", async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({ success: true, data: [], count: 0 }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            success: true,
            data: { id: "p3", name: "New Project", description: null },
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          success: true,
          data: [
            {
              id: "p3",
              name: "New Project",
              description: null,
              created_at: "2025-01-03T00:00:00Z",
              updated_at: "2025-01-03T00:00:00Z",
            },
          ],
          count: 1,
        }),
      );

    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());

    // Open the create modal.
    await userEvent.click(screen.getAllByRole("button", { name: /Create Project/ })[0]);
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Project name"), "New Project");
    await userEvent.click(dialog.getByRole("button", { name: "Create Project" }));

    const [createUrl, createInit] = mockFetch.mock.calls.find(
      (c) => String(c[0]).endsWith("/api/v1/projects") && c[1]?.method === "POST",
    )! as [string, RequestInit];
    expect(createUrl).toBe("http://localhost:8000/api/v1/projects");
    expect(JSON.parse(createInit.body as string)).toEqual({
      name: "New Project",
      description: null,
    });
  });

  it("shows an inline error when creation fails", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ success: true, data: [], count: 0 }))
      .mockResolvedValueOnce(jsonResponse({ detail: "Name is required." }, 422));

    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());

    await userEvent.click(screen.getAllByRole("button", { name: /Create Project/ })[0]);
    const dialog = within(await screen.findByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Project name"), "X");
    await userEvent.click(dialog.getByRole("button", { name: "Create Project" }));

    await waitFor(() =>
      expect(screen.getByText("Name is required.")).toBeInTheDocument(),
    );
  });

  it("disables the create button in the modal while the name is empty", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: [], count: 0 }));
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());
    await userEvent.click(screen.getAllByRole("button", { name: /Create Project/ })[0]);
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByRole("button", { name: "Create Project" })).toBeDisabled();
  });
});
