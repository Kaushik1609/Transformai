/**
 * Phase 9 tests — Results panel.
 *
 * Renders one card per output for every supported output type, plus the
 * loading, empty, generating, and failed states.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("shows a copy button and DOCX/PDF export buttons for text outputs", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "o-summary",
            output_type: "summary",
            text_content: "The executive summary body.",
          }),
        ]}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Copy to clipboard" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /DOCX/ }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PDF/ })).toBeInTheDocument();
  });

  it("does not render export buttons for non-summary/advisory outputs", async () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "o-linkedin",
            output_type: "linkedin",
            text_content: "A LinkedIn post draft.",
          }),
        ]}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Copy to clipboard" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /DOCX/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /PDF/ })).not.toBeInTheDocument();
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

  // Phase 11M — artifact integrity badge.
  it("shows a recorded integrity badge when provenance was recorded", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "o-integrity",
            output_type: "summary",
            text_content: "Body.",
            output_metadata: {
              integrity: { status: "recorded", provider: "fake" },
            },
          }),
        ]}
      />,
    );
    // IntegrityBadge (with aria-hidden icons) exposes the label text.
    expect(screen.getAllByText("Integrity").length).toBeGreaterThan(0);
  });

  it("shows an integrity badge for a non-recorded status", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "o-integrity2",
            output_type: "summary",
            text_content: "Body.",
            output_metadata: {
              integrity: { status: "unavailable", provider: "none" },
            },
          }),
        ]}
      />,
    );
    expect(screen.getAllByText("Integrity").length).toBeGreaterThan(0);
  });

  it("hides the integrity badge when no integrity metadata exists", () => {
    render(
      <ResultsPanel
        outputs={[createOutput({ id: "o-none", output_type: "summary" })]}
      />,
    );
    expect(screen.queryAllByText("Integrity")).toHaveLength(0);
  });

  // Phase 11N — evidence / fact verification.
  it("shows a 'Verify facts' button for completed outputs", () => {
    render(
      <ResultsPanel
        outputs={[createOutput({ id: "o-fact", output_type: "summary" })]}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Verify facts" }),
    ).toBeInTheDocument();
  });

  it("does not show a 'Verify facts' button for failed outputs", () => {
    render(
      <ResultsPanel
        outputs={[
          createOutput({ id: "o-fail", output_type: "summary", status: "failed" }),
        ]}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Verify facts" }),
    ).not.toBeInTheDocument();
  });

  it("runs fact verification and renders the report on success", async () => {
    const report = {
      success: true,
      data: {
        report_id: "r1",
        output_id: "o1",
        overall_status: "warning",
        summary: "2 of 3 claims supported by source evidence.",
        claims_checked: 3,
        claims_supported: 2,
        claims_contradicted: 1,
        claims_unverified: 0,
        claims: [
          {
            id: "c1",
            text: "The system supports 500 concurrent users.",
            claim_type: "explicit",
            verdict: "SUPPORTED",
            reason: "Matches retrieved source evidence.",
            overlap: 0.9,
            evidence: [
              {
                source_id: "s1",
                chunk_id: "chunk1",
                chunk_index: 0,
                evidence: "Supports up to 500 users.",
                relevance_score: 0.8,
                overlap: 0.9,
                numeric_conflict: false,
                date_conflict: false,
              },
            ],
          },
          {
            id: "c2",
            text: "The system supports 50000 users.",
            claim_type: "explicit",
            verdict: "CONTRADICTED",
            reason: "Numeric claim conflicts with source evidence.",
            overlap: 0.9,
            evidence: [],
          },
        ],
      },
    };
    mockFetch.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/verify-facts")) {
        return Promise.resolve(jsonResponse(report));
      }
      return Promise.resolve(
        jsonResponse({ success: true, data: [], count: 0 }),
      );
    });

    render(
      <ResultsPanel
        outputs={[createOutput({ id: "o1", output_type: "summary" })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Verify facts" }));

    expect(
      await screen.findByText("2 of 3 claims supported by source evidence."),
    ).toBeInTheDocument();
    expect(screen.getByText("SUPPORTED")).toBeInTheDocument();
    expect(screen.getByText("CONTRADICTED")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Verify facts" })).not.toBeInTheDocument();
  });

  it("surfaces an error if fact verification fails", async () => {
    mockFetch.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/verify-facts")) {
        return Promise.resolve(jsonResponse({ detail: "boom" }, 409));
      }
      return Promise.resolve(
        jsonResponse({ success: true, data: [], count: 0 }),
      );
    });

    render(
      <ResultsPanel
        outputs={[createOutput({ id: "o2", output_type: "summary" })]}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Verify facts" }));

    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Verify facts" }),
    ).toBeInTheDocument();
  });
});