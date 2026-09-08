/**
 * Phase 12D-G tests — Security activity log (read-only, owner-scoped).
 */
import { render, screen, waitFor } from "@testing-library/react";
import { SecurityActivity } from "@/components/verification";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const events = {
  success: true,
  count: 2,
  data: [
    {
      event_type: "malware_scan_completed",
      outcome: "allowed",
      timestamp: "2025-01-01T10:00:00Z",
      user_id: null,
      project_id: "p1",
      source_id: "s1",
      job_id: null,
      reason: "malware_scan_clean",
      details: { scanner: "fake" },
    },
    {
      event_type: "malware_detected",
      outcome: "denied",
      timestamp: "2025-01-01T10:01:00Z",
      user_id: "u1",
      project_id: "p1",
      source_id: "s2",
      job_id: null,
      reason: "malware_detected",
      details: { scanner: "fake" },
    },
  ],
};

beforeEach(() => {
  mockFetch.mockReset();
});

describe("SecurityActivity", () => {
  it("renders the owner-scoped event list with outcomes", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse(events));
    render(<SecurityActivity projectId="p1" />);

    await waitFor(() =>
      expect(screen.getByText("Security activity")).toBeInTheDocument(),
    );
    expect(screen.getByText("malware_scan_completed")).toBeInTheDocument();
    expect(screen.getByText("malware_detected")).toBeInTheDocument();
    expect(screen.getByText("allowed")).toBeInTheDocument();
    expect(screen.getByText("denied")).toBeInTheDocument();
    expect(screen.getByText("2 events")).toBeInTheDocument();
  });

  it("shows an empty state when no events are recorded", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ success: true, count: 0, data: [] }),
    );
    render(<SecurityActivity projectId="p1" />);

    await waitFor(() =>
      expect(
        screen.getByText("No security events recorded for your scope yet."),
      ).toBeInTheDocument(),
    );
  });

  it("surfaces fetch errors", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Forbidden." }, 403));
    render(<SecurityActivity projectId="p2" />);

    await waitFor(() =>
      expect(screen.getByText("Forbidden.")).toBeInTheDocument(),
    );
  });
});