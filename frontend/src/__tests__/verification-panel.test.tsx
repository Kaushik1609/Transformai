/**
 * Phase 9 tests — Verification panel.
 *
 * Covers the pending Phase 8 state display, real results display, the empty
 * (no record) state, and fetch errors.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { VerificationPanel } from "@/components/verification";
import type { VerificationResultResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const pendingRecord: VerificationResultResponse = {
  id: "v1",
  output_id: "o1",
  overall_status: "pending",
  claims_checked: 0,
  claims_supported: 0,
  grounding_score: null,
  consistency_score: null,
  details: { status: "pending_phase8" },
  warnings: {},
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
  details: {},
  warnings: ["Claim 2 is only partially supported."] as unknown as Record<
    string,
    unknown
  >,
  created_at: "2025-01-01T00:00:00Z",
};

beforeEach(() => {
  mockFetch.mockReset();
});

describe("VerificationPanel", () => {
  it("shows the pending Phase 8 state clearly", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: [pendingRecord], count: 1 }),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() =>
      expect(
        screen.getByText("Verification pending — Phase 8 engine not implemented"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("renders scores, claims, and warnings for real results", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, data: [warningRecord], count: 1 }),
    );
    render(<VerificationPanel outputId="o1" />);

    await waitFor(() => expect(screen.getByText("Verification")).toBeInTheDocument());
    expect(screen.getByText("warning")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();
    expect(screen.getByText("0.8")).toBeInTheDocument();
    expect(screen.getByText("0.9")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(
      screen.getByText("Claim 2 is only partially supported."),
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