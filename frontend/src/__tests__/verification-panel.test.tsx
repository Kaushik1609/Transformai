/**
 * Phase 9 tests — Verification panel.
 *
 * Covers the passed state, the warning state with structured warning items,
 * the empty (no record) state, and fetch errors.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { VerificationPanel } from "@/components/verification";
import type { VerificationResultResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const passedRecord: VerificationResultResponse = {
  id: "v1",
  output_id: "o1",
  overall_status: "passed",
  claims_checked: 1,
  claims_supported: 1,
  grounding_score: 1.0,
  consistency_score: 1.0,
  details: { status: "completed" },
  warnings: {
    status: "passed",
    message: "All claims supported by source.",
    items: [],
    count: 0,
  },
  created_at: "2025-01-01T00:00:00Z",
};

const warningRecord: VerificationResultResponse = {
  id: "v1",
  output_id: "o1",
  overall_status: "warning",
  claims_checked: 4,
  claims_supported: 2,
  grounding_score: 0.8,
  consistency_score: 0.9,
  details: { status: "completed" },
  warnings: {
    status: "warning",
    message: "Some claims are not fully grounded.",
    items: [
      {
        type: "weakly_supported_claim",
        severity: "warning",
        message: "Claim 2 is only partially supported.",
        claim_text: "The platform scales linearly.",
        evidence: null,
        chunk_index: 0,
      },
      {
        type: "numeric_mismatch",
        severity: "error",
        message: "Claim number 500 does not match the source.",
        claim_text: "The system supports 50,000 concurrent users.",
        evidence: "500",
        chunk_index: null,
      },
    ],
    count: 2,
  },
  created_at: "2025-01-01T00:00:00Z",
};

beforeEach(() => {
  mockFetch.mockReset();
});

describe("VerificationPanel", () => {
  it("renders a passed verification result with percentage scores", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: [passedRecord], count: 1 }),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() => expect(screen.getByText("Verification")).toBeInTheDocument());
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();
    expect(screen.getAllByText("100%")).toHaveLength(2);
    expect(screen.getByText("Consistency")).toBeInTheDocument();
    expect(screen.getAllByText("1")).toHaveLength(2);
  });

  it("renders structured warnings and percentage scores for real results", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: [warningRecord], count: 1 }),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() => expect(screen.getByText("Verification")).toBeInTheDocument());
    expect(screen.getByText("warning")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(
      screen.getByText("Claim 2 is only partially supported."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Claim number 500 does not match the source."),
    ).toBeInTheDocument();
  });

  it("treats a 404 as 'no record yet' instead of an error", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "No verification record exists." }, 404),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() =>
      expect(screen.getByText("No verification results yet.")).toBeInTheDocument(),
    );
  });

  it("surfaces fetch errors", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Backend unavailable." }, 503),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() =>
      expect(screen.getByText("Backend unavailable.")).toBeInTheDocument(),
    );
  });
});