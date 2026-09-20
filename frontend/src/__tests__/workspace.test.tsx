/**
 * Phase 9 tests — Transformation workspace (end-to-end integration).
 *
 * Exercises the full UI journey with a fake backend: idle/empty state,
 * processing state, full generate → poll → results → verification → download
 * flow, failed jobs, and load-error retry.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TransformationWorkspace } from "@/components/workspace";
import type {
  ConfigurationResponse,
  OutputResponse,
  SourceResponse,
  TransformationJobResponse,
} from "@/lib/api";
import { FakeBackend, jsonResponse } from "./helpers";

const PROJECT_ID = "11111111-1111-1111-1111-111111111111";

const readySource: SourceResponse = {
  id: "s1",
  project_id: PROJECT_ID,
  source_type: "text",
  original_filename: null,
  storage_key: null,
  mime_type: "text/plain",
  file_size: 842,
  language: "en",
  status: "ready",
  source_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
};

const processingSource: SourceResponse = {
  ...readySource,
  id: "s2",
  status: "processing",
};

const config: ConfigurationResponse = {
  id: "c1",
  project_id: PROJECT_ID,
  target_audience: "technology executives",
  tone: "professional",
  language: "English",
  detail_level: "standard",
  communication_objective: "decision support",
  content_style: null,
  custom_instructions: null,
  created_at: "2025-01-01T00:00:00Z",
};

const queuedJob: TransformationJobResponse = {
  id: "22222222-2222-2222-2222-222222222222",
  project_id: PROJECT_ID,
  source_id: "s1",
  configuration_id: "c1",
  requested_outputs: { output_types: ["summary", "video"] },
  status: "queued",
  progress: 0,
  error_message: null,
  started_at: null,
  completed_at: null,
  created_at: "2025-01-01T00:00:00Z",
};

const outputs: OutputResponse[] = [
  {
    id: "o-summary",
    job_id: "22222222-2222-2222-2222-222222222222",
    output_type: "summary",
    status: "completed",
    structured_content: null,
    storage_key: "sum/summary.txt",
    mime_type: "text/plain",
    text_content: "The board summary for Q3.",
    output_metadata: null,
    created_at: "2025-01-01T00:00:00Z",
  },
  {
    id: "o-video",
    job_id: "22222222-2222-2222-2222-222222222222",
    output_type: "video",
    status: "completed",
    structured_content: null,
    storage_key: "vid/brief.pdf",
    mime_type: "application/pdf",
    text_content: null,
    output_metadata: { artifact: "video", subtitle_storage_key: "vid/brief.srt" },
    created_at: "2025-01-01T00:00:00Z",
  },
];

function renderWorkspace(backend = new FakeBackend(PROJECT_ID)) {
  render(
    <TransformationWorkspace projectId={PROJECT_ID} pollIntervalMs={50} />,
  );
  return backend;
}

describe("TransformationWorkspace", () => {
  it("shows the idle/empty state with readiness hints", async () => {
    global.fetch = new FakeBackend(PROJECT_ID).handler() as unknown as typeof fetch;
    renderWorkspace();

    await waitFor(() => expect(screen.getByText("No source yet")).toBeInTheDocument());
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(screen.getByText(/Add a source first/)).toBeInTheDocument();
    expect(screen.getByText(/Save a configuration/)).toBeInTheDocument();
    expect(screen.getByText(/Select at least one output type/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transform" })).toBeDisabled();
    expect(screen.getByText("1 · Source")).toBeInTheDocument();
    expect(screen.getByText("4 · Transform")).toBeInTheDocument();
  });

  it("shows the processing state for a non-ready source", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    backend.seedSource(processingSource);
    backend.seedConfig(config);
    global.fetch = backend.handler() as unknown as typeof fetch;

    renderWorkspace(backend);

    await waitFor(() => expect(screen.getByText("Processing source…")).toBeInTheDocument());
    expect(
      screen.getByText("Processing source… you can continue configuring while it completes."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Transform" })).toBeDisabled();
    expect(screen.getByText(/Wait for the source to become ready/)).toBeInTheDocument();
  });

  it("runs the full generate → poll → results → verification → download flow", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    backend.seedSource(readySource);
    backend.seedConfig(config);
    backend.seedOutputs(outputs);
    global.fetch = backend.handler() as unknown as typeof fetch;

    renderWorkspace(backend);

    // Workspace loaded with source + saved config.
    await waitFor(() => expect(screen.getByText("Direct text")).toBeInTheDocument());
    expect(screen.getByText("Demo Project")).toBeInTheDocument();
    expect(
      screen.getByText(/Saved: audience “technology executives”/),
    ).toBeInTheDocument();

    // Select outputs.
    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    await userEvent.click(screen.getByRole("checkbox", { name: /Video/ }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();

    // Generate.
    await userEvent.click(screen.getByRole("button", { name: "Transform" }));

    // Generating state (job queued by the fake backend).
    await waitFor(
      () =>
        expect(screen.getAllByText("Transforming…").length).toBeGreaterThan(0),
      { interval: 10 },
    );
    expect(screen.getByText("In progress…")).toBeInTheDocument();

    // Polled to completion → results + verification.
    await waitFor(
      () =>
        expect(screen.getAllByText(/^Completed$/).length).toBeGreaterThan(0),
      { timeout: 4000 },
    );
    expect(screen.getByText("100%")).toBeInTheDocument();
    await waitFor(
      () => expect(screen.getByText("The board summary for Q3.")).toBeInTheDocument(),
      { timeout: 2000 },
    );

    // Verification (empty record list from Phase 8 stub).
    await waitFor(
      () => expect(screen.getAllByText("No verification results yet.")).toHaveLength(2),
      { timeout: 4000 },
    );

    // Downloads available per artifact metadata.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /TXT/ })).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /Subtitles \(SRT\)/ })).toBeInTheDocument();
  });

  it("shows the failed state with the job error", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    backend.seedSource(readySource);
    backend.seedConfig(config);
    backend.jobOnCreate = {
      ...queuedJob,
      status: "failed",
      progress: 100,
      error_message: "Ollama inference timed out.",
    };
    global.fetch = backend.handler() as unknown as typeof fetch;

    renderWorkspace(backend);

    await waitFor(() => expect(screen.getByText("Direct text")).toBeInTheDocument());

    await userEvent.click(
      screen.getByRole("checkbox", { name: /Summary/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Transform" }));

    await waitFor(
      () =>
        expect(screen.getAllByText(/^Failed$/).length).toBeGreaterThan(0),
      { timeout: 2000 },
    );
    expect(screen.getByText("Ollama inference timed out.")).toBeInTheDocument();
    expect(screen.getByText("No outputs generated yet.")).toBeInTheDocument();
  });

  it("shows a friendly load error on 5xx and recovers on retry", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    const handler = backend.handler() as unknown as typeof fetch;
    let failed = true;
    global.fetch = (async (input: RequestInfo | Request, init?: RequestInit) => {
      if (failed) {
        return jsonResponse({ detail: "Internal Server Error" }, 503);
      }
      return handler(input as globalThis.Request, init);
    }) as unknown as typeof fetch;

    renderWorkspace(backend);

    await waitFor(() =>
      expect(screen.getByText("Failed to load the workspace.")).toBeInTheDocument(),
    );

    failed = false;
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(screen.getByText("No source yet")).toBeInTheDocument());
  });

  it("loads outputs for a job selected from the transformation history", async () => {
    const backend = new FakeBackend(PROJECT_ID);
    backend.seedSource(readySource);
    backend.seedConfig(config);
    backend.seedOutputs(outputs);
    const historicJob: TransformationJobResponse = {
      ...queuedJob,
      id: "c0c0c0c0-c0c0-c0c0-c0c0-c0c0c0c0c0c0",
      status: "completed",
      progress: 100,
      started_at: "2025-01-01T00:00:00Z",
      completed_at: "2025-01-01T00:02:00Z",
    };
    backend.history = [historicJob];
    global.fetch = backend.handler() as unknown as typeof fetch;

    renderWorkspace(backend);

    await waitFor(() => expect(screen.getByText("Direct text")).toBeInTheDocument());

    // No results before selection.
    expect(screen.queryByText("The board summary for Q3.")).not.toBeInTheDocument();

    // Select the historical job from the history panel.
    await userEvent.click(await screen.findByText(/Job c0c0c0c0/));

    await waitFor(
      () => expect(screen.getByText("The board summary for Q3.")).toBeInTheDocument(),
      { timeout: 2000 },
    );
    expect(
      screen.getAllByText(/^Completed$/).length,
    ).toBeGreaterThan(0);
  });
});