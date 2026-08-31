/**
 * Phase 10 tests — History panel + recent transformations (dashboard).
 *
 * HistoryPanel lists a project's past transformation jobs and lets the user
 * view a historical job; RecentTransformations summarises the most recent job
 * per project on the dashboard.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HistoryPanel, RecentTransformations } from "@/components/history";
import type { TransformationJobResponse } from "@/lib/api";
import { FakeBackend, type FetchMock } from "./helpers";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const makeJob = (
  id: string,
  overrides: Partial<TransformationJobResponse> = {},
): TransformationJobResponse => ({
  id,
  project_id: PROJECT_ID,
  source_id: "s1",
  configuration_id: "c1",
  requested_outputs: { output_types: ["summary", "advisory"] },
  status: "completed",
  progress: 100,
  error_message: null,
  started_at: "2025-01-02T00:00:00Z",
  completed_at: "2025-01-02T00:02:00Z",
  created_at: "2025-01-02T00:00:00Z",
  ...overrides,
});

describe("HistoryPanel", () => {
  const setUp = (history: TransformationJobResponse[]) => {
    const backend = new FakeBackend(PROJECT_ID);
    backend.history = history;
    (global.fetch as unknown as FetchMock) = backend.handler() as unknown as jest.Mock;
  };

  it("lists the project's transformation jobs with status and time", async () => {
    setUp([
      makeJob("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
      makeJob("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", {
        status: "running",
        progress: 40,
      }),
    ]);

    render(<HistoryPanel projectId={PROJECT_ID} onSelectJob={jest.fn()} />);

    expect(await screen.findByText(/Job aaaaaaaa/)).toBeInTheDocument();
    expect(screen.getByText(/Job bbbbbbbb/)).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getAllByText(/Executive Summary/)).toHaveLength(2);
  });

  it("marks the current job and calls onSelectJob when a row is clicked", async () => {
    setUp([
      makeJob("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
      makeJob("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ]);
    const onSelect = jest.fn();

    render(
      <HistoryPanel
        projectId={PROJECT_ID}
        currentJobId="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        onSelectJob={onSelect}
      />,
    );

    await userEvent.click(await screen.findByText(/Job bbbbbbbb/));
    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb" }),
    );
  });

  it("shows the failure message for failed jobs", async () => {
    setUp([
      makeJob("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", {
        status: "failed",
        error_message: "LLM provider timed out",
      }),
    ]);

    render(<HistoryPanel projectId={PROJECT_ID} onSelectJob={jest.fn()} />);

    expect(await screen.findByText(/LLM provider timed out/)).toBeInTheDocument();
  });

  it("renders an empty state when there is no history", async () => {
    setUp([]);
    render(<HistoryPanel projectId={PROJECT_ID} onSelectJob={jest.fn()} />);
    expect(
      await screen.findByText("No transformations yet"),
    ).toBeInTheDocument();
  });

  it("renders an error state with retry on API failure", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    (global.fetch as unknown as FetchMock) = jest.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => ({ detail: "Internal Server Error" }),
    });

    render(<HistoryPanel projectId={PROJECT_ID} onSelectJob={jest.fn()} />);
    expect(
      await screen.findByText("Failed to load transformation history."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});

describe("RecentTransformations", () => {
  it("shows the most recent job per project and links to the workspace", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    // Newest job first (backend order) → the failed job is the one surfaced.
    backend.history = [
      makeJob("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", {
        status: "failed",
        error_message: "Network error",
      }),
      makeJob("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    ];
    (global.fetch as unknown as FetchMock) = backend.handler() as unknown as jest.Mock;

    render(<RecentTransformations projects={backend.projects} />);

    expect(await screen.findByText("Demo Project")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText(/Network error/)).toBeInTheDocument();
    expect(screen.getByRole("link").getAttribute("href")).toBe(
      `/projects/${PROJECT_ID}`,
    );
  });

  it("renders an empty state when no project has history", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    (global.fetch as unknown as FetchMock) = backend.handler() as unknown as jest.Mock;

    render(<RecentTransformations projects={backend.projects} />);
    expect(
      await screen.findByText("No recent transformations"),
    ).toBeInTheDocument();
  });

  it("renders the empty state when given no projects", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    (global.fetch as unknown as FetchMock) = backend.handler() as unknown as jest.Mock;

    render(<RecentTransformations projects={[]} />);
    expect(
      await screen.findByText("No recent transformations"),
    ).toBeInTheDocument();
  });
});