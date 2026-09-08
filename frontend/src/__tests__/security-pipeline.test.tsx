/**
 * Phase 12D-C tests — Security pipeline (7 stages).
 *
 * Stage statuses must be derived from real backend data: source metadata for
 * the file/malware/PII stages, output metadata for the security stage, and
 * structural pipeline invariants for the generation/retrieval stages. A stage
 * is never reported PASSED without the backing signal.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { SecurityPipeline } from "@/components/verification";
import type { OutputResponse, SourceResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

function sourceWith(
  meta: Record<string, unknown> | null,
): SourceResponse {
  return {
    id: "source-1",
    project_id: "11111111-1111-1111-1111-111111111111",
    source_type: "text",
    original_filename: "memo.txt",
    storage_key: "key",
    mime_type: "text/plain",
    file_size: 1024,
    language: "en",
    status: "ready",
    source_metadata: meta,
    created_at: "2025-01-01T00:00:00Z",
  };
}

function completedOutput(
  id: string,
  output_metadata: Record<string, unknown> | null,
): OutputResponse {
  return {
    id,
    job_id: "job",
    output_type: "summary",
    status: "completed",
    structured_content: null,
    text_content: "Summary",
    storage_key: "sum.txt",
    mime_type: "text/plain",
    output_metadata,
    created_at: "2025-01-01T00:00:00Z",
  };
}

const STAGE_LABELS = [
  "File validation",
  "Malware scan",
  "PII scan",
  "Prompt injection defense",
  "RAG source isolation",
  "Output security",
  "Ownership authorization",
];

beforeEach(() => {
  mockFetch.mockReset();
});

describe("SecurityPipeline", () => {
  it("renders all seven stages", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: sourceWith({}),
      }),
    );
    render(
      <SecurityPipeline
        projectId="p1"
        jobSourceId="source-1"
        outputs={[completedOutput("o1", {})]}
      />,
    );
    for (const label of STAGE_LABELS) {
      expect(await screen.findByText(label)).toBeInTheDocument();
    }
  });

  it("shows NOT_APPLICABLE for disabled malware scanning and UNAVAILABLE for PII without a record", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: sourceWith({}) }),
    );
    render(
      <SecurityPipeline projectId="p1" jobSourceId="source-1" outputs={[]} />,
    );
    await waitFor(() => expect(screen.getByText("File validation")).toBeInTheDocument());
    expect(screen.getByText("Malware scan")).toBeInTheDocument();
    expect(screen.getAllByText("NOT_APPLICABLE").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("UNAVAILABLE").length).toBeGreaterThanOrEqual(1);
  });

  it("shows PASSED for a clean malware scan and WARNING for a PII detection", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: sourceWith({
          malware_scan: { status: "clean", scanner: "fake" },
          pii_scan: { detected: true, counts: { email: 1 } },
        }),
      }),
    );
    render(
      <SecurityPipeline
        projectId="p1"
        jobSourceId="source-1"
        outputs={[completedOutput("o1", {})]}
      />,
    );
    await waitFor(() => expect(screen.getByText("Malware scan")).toBeInTheDocument());
    expect(screen.getByText(/Scanned clean by "fake"/)).toBeInTheDocument();
    expect(
      screen.getByText(/Personally identifiable information was detected/),
    ).toBeInTheDocument();
  });

  it("shows WARNING for an infected flag and BLOCKED for a blocked output", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        success: true,
        data: sourceWith({
          malware_scan: { status: "infected", scanner: "fake" },
        }),
      }),
    );
    render(
      <SecurityPipeline
        projectId="p1"
        jobSourceId="source-1"
        outputs={[
          completedOutput("o1", {
            security: { status: "blocked" },
          }),
        ]}
      />,
    );
    await waitFor(() =>
      expect(screen.getByText(/Malware-like content was flagged/)).toBeInTheDocument(),
    );
    expect(screen.getByText("BLOCKED")).toBeInTheDocument();
  });

  it("shows UNAVAILABLE for a source that cannot be loaded", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "not found" }, 404));
    render(
      <SecurityPipeline
        projectId="p1"
        jobSourceId="missing"
        outputs={[]}
      />,
    );
    await waitFor(() => expect(screen.getByText("File validation")).toBeInTheDocument());
    expect(screen.getByText(/No source is attached to this job/)).toBeInTheDocument();
  });
});