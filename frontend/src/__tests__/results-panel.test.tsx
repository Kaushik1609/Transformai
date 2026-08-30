/**
 * Phase 9 tests — Results panel.
 *
 * Renders one card per output for every supported output type, plus the
 * loading, empty, generating, and failed states.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { ResultsPanel } from "@/components/results";
import type { OutputResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const createOutput = (overrides: Partial<OutputResponse>): OutputResponse => ({
  id: "o1",
  job_id: "j1",
  output_type: "summary",
  status: "completed",
  structured_content: null,
  storage_key: null,
  mime_type: null,
  text_content: null,
  output_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  mockFetch.mockReset();
  // VerificationPanel fetches for each completed output.
  mockFetch.mockResolvedValue(jsonResponse({ success: true, data: [], count: 0 }));
});

describe("ResultsPanel", () => {
  it("renders the loading placeholder", () => {
    render(<ResultsPanel outputs={[]} loading />);
    expect(screen.getByText("Loading outputs…")).toBeInTheDocument();
  });

  it("renders an empty state", () => {
    render(<ResultsPanel outputs={[]} />);
    expect(screen.getByText("No outputs generated yet.")).toBeInTheDocument();
  });

  it("renders one completed card per output type", async () => {
    const outputs: OutputResponse[] = [
      createOutput({
        id: "o-summary",
        output_type: "summary",
        text_content: "The executive summary body.",
      }),
      createOutput({
        id: "o-linkedin",
        output_type: "linkedin",
        text_content: "A LinkedIn post draft.",
      }),
      createOutput({
        id: "o-x",
        output_type: "x",
        text_content: "An X post draft.",
      }),
      createOutput({
        id: "o-advisory",
        output_type: "advisory",
        text_content: "Advisory notes.",
      }),
    ];

    render(<ResultsPanel outputs={outputs} />);

    expect(screen.getByText("Executive Summary")).toBeInTheDocument();
    expect(screen.getByText("LinkedIn Post")).toBeInTheDocument();
    expect(screen.getByText("X Post")).toBeInTheDocument();
    expect(screen.getByText("Advisory Note")).toBeInTheDocument();

    expect(screen.getByText("The executive summary body.")).toBeInTheDocument();
    expect(screen.getByText("A LinkedIn post draft.")).toBeInTheDocument();

    // Each completed card fetches verification.
    await waitFor(() =>
      expect(screen.getAllByText("No verification results yet.")).toHaveLength(4),
    );
  });

  it("shows duplicated status badges for each output", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({ id: "a", output_type: "summary" }),
          createOutput({ id: "b", output_type: "video" }),
        ]}
      />,
    );
    expect(screen.getAllByText("completed")).toHaveLength(2);
  });

  it("shows a 'generating' state for outputs still in progress", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({ id: "g", output_type: "infographic", status: "generating" }),
        ]}
      />,
    );
    expect(screen.getByText("This output is still being generated…")).toBeInTheDocument();
  });

  it("shows a failed state without download options", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "f",
            output_type: "presentation",
            status: "failed",
            storage_key: null,
            mime_type: null,
          }),
        ]}
      />,
    );
    expect(
      screen.getByText("This output failed to generate."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders binary outputs (infographic/presentation/video) without a text preview", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "v",
            output_type: "video",
            output_metadata: { artifact: "video", subtitle_storage_key: "x.srt" },
          }),
        ]}
      />,
    );
    expect(screen.queryByText(/Content prepared/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Subtitles \(SRT\)/ }),
    ).toBeInTheDocument();
  });
});