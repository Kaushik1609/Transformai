/**
 * UI-7 — Project Source Library tests.
 *
 * The library maps real backend source records to bounded, honest readouts:
 * processing status (Ready/Processing/Failed/Unavailable), malware signals
 * (CLEAN/BLOCKED/UNAVAILABLE) and PII signals (DETECTED/NOT_DETECTED/
 * UNAVAILABLE). Missing scan results stay UNAVAILABLE and raw PII contents
 * are never exposed.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  ProjectSourceLibrary,
  sourceSecuritySignals,
  sourceStatusLabel,
} from "@/components/projects";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const source = (
  id: string,
  overrides: Record<string, unknown> = {},
) => ({
  id,
  project_id: "p1",
  source_type: "file",
  original_filename: `${id}.pdf`,
  storage_key: `k-${id}`,
  mime_type: "application/pdf",
  file_size: 20480,
  language: "en",
  status: "ready",
  source_metadata: {
    malware_scan: { status: "clean", scanner: "clamav" },
    pii_scan: { detected: false, counts: {} },
  },
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

describe("ProjectSourceLibrary", () => {
  it("maps source status to Ready/Processing/Failed/Unavailable honestly", () => {
    expect(sourceStatusLabel("ready")).toBe("Ready");
    expect(sourceStatusLabel("processing")).toBe("Processing");
    expect(sourceStatusLabel("uploaded")).toBe("Processing");
    expect(sourceStatusLabel("failed")).toBe("Failed");
    expect(sourceStatusLabel(undefined)).toBe("Unavailable");
  });

  it("maps security metadata to bounded signals without raw PII values", () => {
    expect(
      sourceSecuritySignals(
        source("clean", {
          source_metadata: {
            malware_scan: { status: "clean", scanner: "clamav" },
            pii_scan: { detected: true, counts: { email: 3 } },
          },
        }),
      ),
    ).toEqual({ malware: "CLEAN", pii: "DETECTED" });
    expect(
      sourceSecuritySignals(
        source("dirty", {
          source_metadata: {
            malware_scan: { status: "infected", scanner: "clamav" },
            pii_scan: { detected: false, counts: {} },
          },
        }),
      ),
    ).toEqual({ malware: "BLOCKED", pii: "NOT_DETECTED" });
    // Absent scans are never invented as clean.
    expect(
      sourceSecuritySignals(source("unknown", { source_metadata: null })),
    ).toEqual({ malware: "UNAVAILABLE", pii: "UNAVAILABLE" });
  });

  it("renders sources with status and security badges", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({
        success: true,
        data: [
          source("alpha", { status: "ready", original_filename: "Alpha.pdf" }),
          source("beta", {
            status: "failed",
            original_filename: "Beta.pdf",
            source_metadata: {
              malware_scan: { status: "infected", scanner: "clamav" },
              pii_scan: { detected: true, counts: { email: 1 } },
            },
          }),
        ],
        count: 2,
      }),
    );
    render(<ProjectSourceLibrary projectId="p1" />);

    await waitFor(() => expect(screen.getByText("Alpha.pdf")).toBeInTheDocument());
    expect(screen.getByText("Beta.pdf")).toBeInTheDocument();
    expect(screen.getAllByText("Ready").length).toBe(1);
    expect(screen.getAllByText("Failed").length).toBe(1);
    expect(screen.getAllByText("Malware CLEAN").length).toBe(1);
    expect(screen.getAllByText("Malware BLOCKED").length).toBe(1);
    expect(screen.getAllByText("PII DETECTED").length).toBe(1);
    expect(screen.getAllByText("PII NOT_DETECTED").length).toBe(1);
    // Raw PII values are never surfaced (no field name, no contents).
    expect(screen.queryByText(/email/i)).not.toBeInTheDocument();
  });

  it("keeps missing scans UNAVAILABLE, never a fabricated clean pass", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({
        success: true,
        data: [source("unknown", { source_metadata: null })],
        count: 1,
      }),
    );
    render(<ProjectSourceLibrary projectId="p1" />);

    await waitFor(() =>
      expect(screen.getAllByText("Malware UNAVAILABLE").length).toBe(1),
    );
    expect(screen.getAllByText("PII UNAVAILABLE").length).toBe(1);
    expect(screen.queryByText(/Malware CLEAN/)).not.toBeInTheDocument();
  });

  it("marks the selected source and calls onTransformSource with its id", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({
        success: true,
        data: [source("alpha", { original_filename: "Alpha.pdf" })],
        count: 1,
      }),
    );
    const onTransform = jest.fn();
    render(
      <ProjectSourceLibrary
        projectId="p1"
        selectedSourceId="alpha"
        onTransformSource={onTransform}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Alpha.pdf")).toBeInTheDocument(),
    );
    const button = screen.getByRole("button", {
      name: "Transform with this source",
    });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Selected")).toBeInTheDocument();

    await userEvent.click(button);
    expect(onTransform).toHaveBeenCalledWith("alpha");
  });

  it("disables transform for sources that are not Ready", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({
        success: true,
        data: [source("beta", { status: "processing" })],
        count: 1,
      }),
    );
    const onTransform = jest.fn();
    render(
      <ProjectSourceLibrary projectId="p1" onTransformSource={onTransform} />,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Transform with this source" }),
      ).toBeDisabled(),
    );
    // Disabled buttons never fire clicks — no transform flow starts.
    expect(onTransform).not.toHaveBeenCalled();
  });

  it("shows an empty state when the project has no sources", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({ success: true, data: [], count: 0 }),
    );
    render(<ProjectSourceLibrary projectId="p1" />);

    await waitFor(() =>
      expect(screen.getByText("No sources yet")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(
        "Add a source in the transformation workspace to begin.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an error state with retry when sources fail to load", async () => {
    mockFetch.mockImplementation(async () =>
      jsonResponse({ detail: "boom" }, 503),
    );
    render(<ProjectSourceLibrary projectId="p1" />);

    await waitFor(() =>
      expect(screen.getByText("Failed to load sources.")).toBeInTheDocument(),
    );

    mockFetch.mockImplementation(async () =>
      jsonResponse({ success: true, data: [source("alpha")], count: 1 }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() =>
      expect(screen.getByText("alpha.pdf")).toBeInTheDocument(),
    );
  });
});