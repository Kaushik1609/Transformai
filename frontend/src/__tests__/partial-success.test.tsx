/**
 * Product hardening — partial-success acceptance tests.
 *
 * Covers the PRIMARY ACCEPTANCE CRITERION: selecting all seven outputs must
 * yield ONE job whose individual output states are shown (e.g. "3 / 7 outputs
 * completed") and a partial-success job (Summary/LinkedIn/X completed,
 * Advisory/Presentation/Infographic/Video failed) must NEVER hide the failed
 * outputs and must surface safe failure details. Also covers all-failed,
 * artifact-availability gating ("Not available"), and historical partial
 * transformations.
 */
import { render, screen, waitFor } from "@testing-library/react";
import {
  ResultsPanel,
  TransformationProgress,
  UnifiedResults,
} from "@/components/results";
import { HistoryPanel } from "@/components/history";
import type { OutputResponse, TransformationJobResponse } from "@/lib/api";
import { outputTypeShortLabel } from "@/lib/outputTypes";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const SEVEN_TYPES = [
  "summary",
  "linkedin",
  "x",
  "advisory",
  "infographic",
  "presentation",
  "video",
];

const jobWith = (overrides: Partial<TransformationJobResponse>) => ({
  id: "22222222-2222-2222-2222-222222222222",
  project_id: "11111111-1111-1111-1111-111111111111",
  source_id: "source",
  configuration_id: "config",
  requested_outputs: { output_types: SEVEN_TYPES },
  status: "completed",
  progress: 100,
  error_message: null,
  started_at: "2025-01-01T00:00:00Z",
  completed_at: "2025-01-01T00:01:00Z",
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

const completedOutput = (type: string): OutputResponse => ({
  id: `out-${type}`,
  job_id: "22222222-2222-2222-2222-222222222222",
  output_type: type,
  status: "completed",
  structured_content: null,
  text_content: `Completed ${type} content.`,
  storage_key: `artifacts/${type}.txt`,
  mime_type: "text/plain",
  output_metadata: null,
  created_at: "2025-01-01T00:01:00Z",
});

const failedOutput = (type: string): OutputResponse => ({
  id: `out-${type}`,
  job_id: "22222222-2222-2222-2222-222222222222",
  output_type: type,
  status: "failed",
  structured_content: null,
  text_content: null,
  storage_key: null,
  mime_type: null,
  output_metadata: {
    resilience: {
      provider: "openai-compatible",
      model: "big-pickle",
      attempts: 3,
      max_attempts: 3,
      retryable: true,
      last_error_type: "timeout",
      last_error_message: "Provider timed out after retries.",
      retried: true,
      used_fallback: false,
      final_status: "failed",
    },
  },
  created_at: "2025-01-01T00:01:00Z",
});

const PARTIAL_OUTPUTS = [
  completedOutput("summary"),
  completedOutput("linkedin"),
  completedOutput("x"),
  failedOutput("advisory"),
  failedOutput("infographic"),
  failedOutput("presentation"),
  failedOutput("video"),
];

interface ConsistencyLike {
  job_id: string;
  trust_statuses: unknown[];
  cross_output: {
    status: string;
    completed_output_count: number;
    conflicts: unknown[];
    checked_pairs: number;
    note: string;
  };
}

const JOB_ID = "22222222-2222-2222-2222-222222222222";

/**
 * Default fetch handler for these suites. The UI-6 trust cockpit now composes
 * the existing panels and auto-loads the consistency + security-events
 * endpoints, so those routes return realistic (unremarkable) payloads while
 * everything else keeps the original empty defaults.
 */
function cockpitHandler(consistency?: ConsistencyLike) {
  return async (input: RequestInfo | URL) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");

    if (path.endsWith("/consistency")) {
      return jsonResponse({
        success: true,
        data: consistency ?? {
          job_id: JOB_ID,
          trust_statuses: [],
          cross_output: {
            status: "CONSISTENT",
            completed_output_count: 0,
            conflicts: [],
            checked_pairs: 0,
            note: "",
          },
        },
      });
    }
    if (path.endsWith("/security-events")) {
      return jsonResponse({ success: true, count: 0, data: [] });
    }
    if (/^\/api\/v1\/sources\/[^/]+$/.test(path)) {
      return jsonResponse({ success: true, data: null });
    }
    return jsonResponse({ success: true, data: [], count: 0 });
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  // VerificationPanel fetches for each completed output.
  mockFetch.mockImplementation(cockpitHandler());
});

describe("Acceptance: partial success across all seven outputs", () => {
  it("TransformationProgress shows '3 / 7 outputs' and every output state", () => {
    render(
      <TransformationProgress job={jobWith({})} outputs={PARTIAL_OUTPUTS} />,
    );

    expect(screen.getByText("3 / 7 outputs")).toBeInTheDocument();
    // All seven output rows are rendered — the four failures are NOT hidden.
    expect(screen.getByText("Summary")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn")).toBeInTheDocument();
    expect(screen.getByText("X Thread")).toBeInTheDocument();
    expect(screen.getByText("Advisory")).toBeInTheDocument();
    expect(screen.getByText("Infographic")).toBeInTheDocument();
    expect(screen.getByText("Presentation")).toBeInTheDocument();
    expect(screen.getByText("Video Package")).toBeInTheDocument();
    // Three "completed" statuses, four "failed" statuses.
    expect(screen.getAllByText("completed")).toHaveLength(3);
    expect(screen.getAllByText("failed")).toHaveLength(4);
    // Partial-completion summary line.
    expect(
      screen.getByText(/3 outputs completed/),
    ).toBeInTheDocument();
    expect(screen.getByText(/4 outputs failed/)).toBeInTheDocument();
  });

  it("UnifiedResults reports 3 generated and 4 failed for a partial job, and shows the trust cockpit", async () => {
    mockFetch.mockImplementation(
      cockpitHandler({
        job_id: JOB_ID,
        trust_statuses: [],
        cross_output: {
          status: "CONSISTENT",
          completed_output_count: 3,
          conflicts: [],
          checked_pairs: 3,
          note: "",
        },
      }),
    );
    render(
      <UnifiedResults job={jobWith({})} outputs={PARTIAL_OUTPUTS} />,
    );

    expect(screen.getByText("3 outputs generated")).toBeInTheDocument();
    expect(screen.getByText("4 failed")).toBeInTheDocument();
    // All seven tabs present (failures represented as tabs, not hidden).
    for (const type of SEVEN_TYPES) {
      const expected = outputTypeShortLabel(type);
      expect(screen.getByRole("tab", { name: expected })).toBeInTheDocument();
    }

    // UI-6 — the trust cockpit composes the existing verification panels in
    // a single hierarchy and surfaces real consistency data.
    await waitFor(() =>
      expect(
        screen.getByText("Consistent across 3 completed outputs."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Trust status")).toBeInTheDocument();
    expect(screen.getByText("Why this status")).toBeInTheDocument();
    expect(screen.getByText("Cross-output consistency")).toBeInTheDocument();
    expect(screen.getByText("Fact verification")).toBeInTheDocument();
    expect(screen.getByText("Security signals")).toBeInTheDocument();
    expect(screen.getByText("Artifact integrity & provenance")).toBeInTheDocument();
    expect(screen.getByText("What remains unverified")).toBeInTheDocument();
    expect(screen.queryByText(/\d+\.?\d*% safe/)).not.toBeInTheDocument();
    expect(screen.queryByText(/blockchain/i)).not.toBeInTheDocument();
  });

  it("ResultsPanel renders all 7 cards and never hides the 4 failures", async () => {
    render(<ResultsPanel outputs={PARTIAL_OUTPUTS} />);

    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn Post")).toBeInTheDocument();
    expect(screen.getByText("X Post")).toBeInTheDocument();
    expect(screen.getByText("Advisory Note")).toBeInTheDocument();
    expect(screen.getByText("Infographic")).toBeInTheDocument();
    expect(screen.getByText("Presentation")).toBeInTheDocument();
    expect(screen.getByText("Video Package")).toBeInTheDocument();

    // Four failed outputs each show the failure message + safe resilience detail.
    expect(screen.getAllByText("This output failed to generate.")).toHaveLength(4);
    expect(screen.getAllByText("timeout")).toHaveLength(4);
    expect(screen.getAllByText("3 of 3")).toHaveLength(4);
    expect(screen.getAllByText("Exhausted")).toHaveLength(4);
    // The safe, redacted message is surfaced (not a raw trace).
    expect(
      screen.getAllByText("Provider timed out after retries."),
    ).toHaveLength(4);

    // Completed outputs render their text content.
    expect(
      screen.getByText("Completed summary content."),
    ).toBeInTheDocument();

    // Failed outputs get no verification requests; completed ones do.
    await waitFor(() =>
      expect(screen.getAllByText("No verification results yet.")).toHaveLength(3),
    );
  });

  it("renders per-output failure details without exposing raw metadata", () => {
    render(
      <ResultsPanel
        outputs={[
          {
            ...failedOutput("advisory"),
            output_metadata: {
              resilience: {
                attempts: 2,
                max_attempts: 3,
                retryable: true,
                used_fallback: true,
                last_error_type: "rate_limit",
                last_error_message: "Rate limited.",
                provider: "fallback",
              },
            },
          },
        ]}
      />,
    );

    expect(screen.getByText("rate_limit")).toBeInTheDocument();
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByText("Used")).toBeInTheDocument();
    expect(screen.getByText("fallback")).toBeInTheDocument();
    // Raw resilience object must never be rendered as JSON.
    expect(screen.queryByText(/\"attempts\"/)).not.toBeInTheDocument();
  });
});

describe("All outputs failed", () => {
  it("TransformationProgress reports the job could not be completed", () => {
    const allFailed = SEVEN_TYPES.map(failedOutput);
    render(
      <TransformationProgress job={jobWith({})} outputs={allFailed} />,
    );

    expect(screen.getByText("0 / 7 outputs")).toBeInTheDocument();
    expect(
      screen.getByText("The transformation could not be completed."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("failed")).toHaveLength(7);
  });
});

describe("Artifact availability gating", () => {
  it("shows 'Not available' for a completed binary output with no artifact", () => {
    render(
      <ResultsPanel
        outputs={[
          {
            ...completedOutput("presentation"),
            text_content: null,
            storage_key: null,
            mime_type: null,
            output_metadata: null,
          },
        ]}
      />,
    );

    expect(
      screen.getByText("Not available — this output has no downloadable artifact."),
    ).toBeInTheDocument();
  });

  it("does not show 'Not available' when an artifact is available", async () => {
    render(<ResultsPanel outputs={[completedOutput("presentation")]} />);

    expect(
      screen.queryByText("Not available — this output has no downloadable artifact."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Download/ }),
    ).toBeInTheDocument();
  });
});

describe("Historical partial transformation", () => {
  const historyHandler = (job: TransformationJobResponse) =>
    (async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0].replace("http://localhost:8000", "");
      if (/\/api\/v1\/projects\/[^/]+\/transformations$/.test(path)) {
        return jsonResponse({ success: true, data: [job], count: 1 });
      }
      if (/\/api\/v1\/projects\/[^/]+\/sources$/.test(path)) {
        return jsonResponse({ success: true, data: [], count: 0 });
      }
      if (/\/api\/v1\/projects\/[^/]+\/configurations$/.test(path)) {
        return jsonResponse({ success: true, data: [], count: 0 });
      }
      return jsonResponse({ detail: `No route ${path}` }, 404);
    }) as unknown as typeof mockFetch;

  it("HistoryPanel labels a partial job with its composite status", async () => {
    const job = jobWith({});
    mockFetch.mockImplementation(historyHandler(job));
    render(
      <HistoryPanel
        projectId={job.project_id}
        outputsByJobId={{ [job.id]: PARTIAL_OUTPUTS }}
        onSelectJob={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("partial")).toBeInTheDocument());
    expect(screen.getByText(/22222222/)).toBeInTheDocument();
  });

  it("HistoryPanel shows 'failed' for a fully failed job", async () => {
    const allFailed = SEVEN_TYPES.map(failedOutput);
    const job = jobWith({ status: "failed", error_message: "All outputs failed." });
    mockFetch.mockImplementation(historyHandler(job));
    render(
      <HistoryPanel
        projectId={job.project_id}
        outputsByJobId={{ [job.id]: allFailed }}
        onSelectJob={jest.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("failed")).toBeInTheDocument());
  });
});
