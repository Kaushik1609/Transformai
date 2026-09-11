/**
 * UI-9 tests — Artifact inspector.
 *
 * The single-output inspection panel must render ONLY real output data: type
 * identity + status, the generated timestamp and recorded format, per-type
 * previews from structured content, honest action availability (copy/export/
 * download), the full integrity readout, and safe redacted failure details.
 * It must never fabricate trust percentages, file URLs, or content streams.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ArtifactInspector } from "@/components/results";
import type { OutputResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const createOutput = (
  overrides: Partial<OutputResponse> & { output_type: OutputResponse["output_type"] },
): OutputResponse => ({
  id: "o-1",
  job_id: "j1",
  status: "completed",
  structured_content: null,
  storage_key: null,
  mime_type: null,
  text_content: null,
  output_metadata: null,
  created_at: "2025-01-05T10:30:00Z",
  ...overrides,
});

beforeEach(() => {
  mockFetch.mockReset();
  // VerificationPanel fetches per output; empty verifications by default.
  mockFetch.mockResolvedValue(jsonResponse({ success: true, data: [], count: 0 }));
});

describe("ArtifactInspector — header and ledger", () => {
  it("renders the type identity, status badge and integrity badge", () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "summary", text_content: "Body." })}
      />,
    );
    expect(screen.getByRole("heading", { name: "Executive Summary" })).toBeInTheDocument();
    expect(screen.getAllByText("completed").length).toBeGreaterThan(0);
    expect(screen.getByText(/summary · /)).toBeInTheDocument();
    expect(screen.getByText("Integrity · UNAVAILABLE")).toBeInTheDocument();
  });

  it("shows the generated timestamp from the real record", () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "linkedin", mime_type: "text/plain" })}
      />,
    );
    // formatDateTime → toLocaleString; assert via label + non-empty value.
    const generated = screen.getByText("Generated").closest("div");
    expect(generated).not.toBeNull();
    const value = generated?.querySelector("dd");
    expect(value?.textContent).toBeTruthy();
    expect(value?.textContent).not.toBe("—");
    expect(screen.getByText("text/plain")).toBeInTheDocument();
  });

  it("never renders raw storage keys or raw resilience metadata", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "summary",
          storage_key: "artifacts/secret-path/summary.txt",
          output_metadata: {
            resilience: {
              raw_secret_payload: "duplex-credentials",
              attempts: 1,
            },
          },
        })}
      />,
    );
    expect(screen.queryByText(/artifacts\/secret-path/)).not.toBeInTheDocument();
    expect(screen.queryByText(/raw_secret_payload/)).not.toBeInTheDocument();
    expect(screen.queryByText(/duplex-credentials/)).not.toBeInTheDocument();
  });
});

describe("ArtifactInspector — previews", () => {
  it("renders text content for a text-type output", () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "advisory", text_content: "Advisory body text." })}
      />,
    );
    expect(screen.getByText(/Advisory body text./)).toBeInTheDocument();
    expect(screen.getByText("Preview")).toBeInTheDocument();
  });

  it("renders the X thread preview from structured content", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "x",
          structured_content: { thread: ["Tweet one.", "Tweet two."] },
        })}
      />,
    );
    expect(screen.getByText(/Post 1/)).toBeInTheDocument();
    expect(screen.getByText("Tweet one.")).toBeInTheDocument();
    expect(screen.getByText("Tweet two.")).toBeInTheDocument();
  });

  it("renders the slide preview for a presentation output", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "presentation",
          structured_content: {
            title: "Quarterly",
            slides: [{ title: "Slide One", key_message: "Q3 numbers" }],
          },
        })}
      />,
    );
    expect(screen.getByText(/1 slide/)).toBeInTheDocument();
    expect(screen.getByText(/Slide 1/)).toBeInTheDocument();
    expect(screen.getByText("Q3 numbers")).toBeInTheDocument();
  });
});

describe("ArtifactInspector — actions and availability", () => {
  it("offers copy/export/download for a text artifact", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "summary",
          text_content: "Body.",
          storage_key: "artifacts/s.txt",
          mime_type: "text/plain",
        })}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Copy to clipboard" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /DOCX/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /PDF/ })).toBeInTheDocument();
  });

  it("does not offer export for non-summary/advisory outputs", () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "linkedin", text_content: "Post." })}
      />,
    );
    expect(screen.queryByRole("button", { name: /DOCX/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /PDF/ })).not.toBeInTheDocument();
  });

  it("says 'Not available' when a binary output has no artifact, but omits the raw key", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "infographic",
          status: "completed",
          text_content: null,
          storage_key: null,
          mime_type: null,
        })}
      />,
    );
    expect(
      screen.getByText("Not available — this output has no downloadable artifact."),
    ).toBeInTheDocument();
  });

  it("does not gate a completed output with an artifact as unavailable", async () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "video",
          mime_type: "application/pdf",
          storage_key: "artifacts/v.pdf",
          output_metadata: { artifact: "video", subtitle_storage_key: "v.srt" },
        })}
      />,
    );
    expect(
      screen.queryByText(/no downloadable artifact/),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Subtitles \(SRT\)/ }),
    ).toBeInTheDocument();
  });
});

describe("ArtifactInspector — failure, integrity and verification", () => {
  it("renders safe redacted failure details with no actions", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "advisory",
          status: "failed",
          storage_key: null,
          mime_type: null,
          output_metadata: {
            resilience: {
              provider: "openai-compatible",
              attempts: 3,
              max_attempts: 3,
              retryable: true,
              last_error_type: "timeout",
              last_error_message: "Provider timed out after retries.",
              used_fallback: false,
            },
          },
        })}
      />,
    );
    expect(
      screen.getByText("This output failed to generate."),
    ).toBeInTheDocument();
    expect(screen.getByText("timeout")).toBeInTheDocument();
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    expect(screen.getByText("Exhausted")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders the full integrity & provenance readout", () => {
    render(
      <ArtifactInspector
        output={createOutput({
          output_type: "summary",
          output_metadata: {
            integrity: { status: "recorded", provider: "fake", recorded: true },
          },
        })}
      />,
    );
    expect(screen.getByText("Artifact integrity")).toBeInTheDocument();
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("RECORDED")).toBeInTheDocument();
  });

  it("shows verification and fact-verification entry points for completed outputs", async () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "summary", text_content: "Body." })}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Verify facts" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByText("No verification results yet.")).toBeInTheDocument(),
    );
  });

  it("runs fact verification and renders the report", async () => {
    mockFetch.mockImplementation((input) => {
      const url = String(input);
      if (url.endsWith("/verify-facts")) {
        return Promise.resolve(
          jsonResponse({
            success: true,
            data: {
              report_id: "r1",
              output_id: "o-1",
              overall_status: "passed",
              summary: "All claims supported by source evidence.",
              claims_checked: 1,
              claims_supported: 1,
              claims_contradicted: 0,
              claims_unverified: 0,
              claims: [],
            },
          }),
        );
      }
      return Promise.resolve(jsonResponse({ success: true, data: [], count: 0 }));
    });

    render(
      <ArtifactInspector
        output={createOutput({ output_type: "summary", text_content: "Body." })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Verify facts" }));
    expect(
      await screen.findByText("All claims supported by source evidence."),
    ).toBeInTheDocument();
  });

  it("never fabricates trust percentages or blockchain claims", () => {
    render(
      <ArtifactInspector
        output={createOutput({ output_type: "summary", text_content: "Body." })}
      />,
    );
    expect(screen.queryByText(/\d+\.?\d*% safe/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/blockchain/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/trust score|trustScore/i)).not.toBeInTheDocument();
  });
});