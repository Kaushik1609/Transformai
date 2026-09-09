/**
 * UI-6 — Trust / Verification Cockpit tests.
 *
 * The cockpit is a frontend composition layer over existing backend signals.
 * These tests pin the honest mapping: TRUSTED / CAUTION / UNVERIFIED reason
 * display, cross-output consistency states, on-demand fact verification,
 * security stages, artifact integrity and — crucially — that unavailable
 * signals stay unavailable and no trust percentages / blockchain claims are
 * ever fabricated.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TrustCockpit, trustCounts } from "@/components/verification";
import type {
  ConsistencyResultResponse,
  OutputResponse,
  TransformationJobResponse,
  TrustStatusResponse,
} from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const JOB: TransformationJobResponse = {
  id: "job-1",
  project_id: "proj-1",
  source_id: "src-1",
  configuration_id: "cfg-1",
  requested_outputs: { output_types: ["summary", "linkedin"] },
  status: "completed",
  progress: 100,
  error_message: null,
  started_at: "2025-01-01T00:00:00Z",
  completed_at: "2025-01-01T00:01:00Z",
  created_at: "2025-01-01T00:00:00Z",
};

function output(
  id: string,
  type: string,
  options: {
    status?: "completed" | "failed";
    integrity?: { status?: string; digest?: string; recorded?: boolean };
  } = {},
): OutputResponse {
  const { status = "completed", integrity } = options;
  return {
    id,
    job_id: JOB.id,
    output_type: type,
    status,
    structured_content: null,
    text_content: status === "completed" ? `Completed ${type} content.` : null,
    storage_key: status === "completed" ? `artifacts/${id}.txt` : null,
    mime_type: "text/plain",
    output_metadata: integrity
      ? { integrity }
      : status === "failed"
        ? { resilience: { final_status: "failed" } }
        : null,
    created_at: "2025-01-01T00:01:00Z",
  };
}

function trust(
  status: "TRUSTED" | "CAUTION" | "UNVERIFIED",
  reasonCodes: string[],
  signals: TrustStatusResponse["signals"],
  outputType = "summary",
): TrustStatusResponse {
  return {
    status,
    reason_codes: reasonCodes,
    signals,
    output_id: `${outputType}-1`,
    output_type: outputType,
  };
}

function consistency(
  statuses: TrustStatusResponse[],
  cross: ConsistencyResultResponse["cross_output"],
): ConsistencyResultResponse {
  return { job_id: JOB.id, trust_statuses: statuses, cross_output: cross };
}

const CROSS_CONSISTENT = {
  status: "CONSISTENT" as const,
  completed_output_count: 2,
  conflicts: [],
  checked_pairs: 1,
  note: "",
};

/** TRUSTED (summary) + CAUTION (linkedin) — one signal missing per CAUTION. */
const FACT_STATUSES = (): TrustStatusResponse[] => [
  trust(
    "TRUSTED",
    ["GROUNDING_STRONG"],
    [
      {
        category: "grounding",
        present: true,
        status: "positive",
        reason_code: "GROUNDING_STRONG",
        detail: "Source-grounded generation.",
      },
    ],
    "summary",
  ),
  trust(
    "CAUTION",
    ["FACTS_PARTIAL_SUPPORT"],
    [
      {
        category: "fact_verification",
        present: false,
        status: "missing",
        reason_code: "FACTS_PARTIAL_SUPPORT",
        detail: "Some claims lack direct evidence.",
      },
      {
        category: "integrity",
        present: true,
        status: "positive",
        reason_code: "INTEGRITY_RECORDED",
        detail: "Fingerprint recorded.",
      },
    ],
    "linkedin",
  ),
];

/** Every evaluated signal category has a recorded result (nothing missing). */
const ALL_RECORDED_STATUSES = (): TrustStatusResponse[] => [
  trust(
    "TRUSTED",
    ["GROUNDING_STRONG"],
    [
      {
        category: "grounding",
        present: true,
        status: "positive",
        reason_code: "GROUNDING_STRONG",
        detail: "Source-grounded generation.",
      },
    ],
    "summary",
  ),
  trust(
    "CAUTION",
    ["FACTS_PARTIAL_SUPPORT"],
    [
      {
        category: "fact_verification",
        present: true,
        status: "warning",
        reason_code: "FACTS_PARTIAL_SUPPORT",
        detail: "Some claims lack direct evidence.",
      },
    ],
    "linkedin",
  ),
];

interface HandlerOptions {
  consistency?: ConsistencyResultResponse | "error";
  source?: Record<string, unknown> | null;
  securityEvents?: { success: boolean; count: number; data: unknown[] };
  verifyFacts?: { success: boolean; data: unknown };
}

function handler(options: HandlerOptions = {}) {
  const {
    consistency: consistencyResult = consistency([], CROSS_CONSISTENT),
    source = null,
    securityEvents = { success: true, count: 0, data: [] },
  } = options;

  return async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const path = url.split("?")[0].replace("http://localhost:8000", "");
    const method = init?.method ?? "GET";

    if (path.endsWith("/consistency")) {
      if (consistencyResult === "error") {
        return jsonResponse(
          { detail: "Consistency check unavailable." },
          503,
        );
      }
      return jsonResponse({ success: true, data: consistencyResult });
    }
    if (path.endsWith("/security-events")) {
      return jsonResponse(securityEvents);
    }
    if (/^\/api\/v1\/sources\/[^/]+$/.test(path)) {
      return jsonResponse({ success: true, data: source });
    }
    if (/\/outputs\/[^/]+\/verify-facts$/.test(path)) {
      if (method !== "POST") return jsonResponse({ detail: "bad" }, 405);
      if (options.verifyFacts) return jsonResponse(options.verifyFacts);
      return jsonResponse(
        {
          success: true,
          data: {
            report_id: `rep-${path.split("/").pop()}`,
            output_id: "out-summary",
            overall_status: "passed",
            summary: "Claims are supported by project sources.",
            claims_checked: 1,
            claims_supported: 1,
            claims_contradicted: 0,
            claims_unverified: 0,
            claims: [
              {
                id: "claim-1",
                text: "Revenue grew 12%.",
                claim_type: "statistic",
                verdict: "SUPPORTED",
                reason: "Matches source evidence.",
                overlap: 0.9,
                evidence: [],
              },
            ],
          },
        },
        200,
      );
    }
    return jsonResponse({ detail: `No route ${path}` }, 404);
  };
}

beforeEach(() => {
  mockFetch.mockReset();
  localStorage.clear();
});

describe("TrustCockpit — trust status + reasons", () => {
  it("renders TRUSTED status and its backend reason codes", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency(FACT_STATUSES(), CROSS_CONSISTENT),
      }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary-1", "summary", {
            integrity: { status: "recorded", digest: "ab12", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() => expect(screen.getByText("TRUSTED")).toBeInTheDocument());
    expect(screen.getByText("Why this status")).toBeInTheDocument();
    expect(screen.getAllByText("GROUNDING_STRONG").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Reasons reported by the backend"),
    ).toBeInTheDocument();
  });

  it("renders CAUTION status with its warning reason", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency(FACT_STATUSES(), CROSS_CONSISTENT),
      }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary-1", "summary", {
            integrity: { status: "recorded", digest: "ab12", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() => expect(screen.getByText("CAUTION")).toBeInTheDocument());
    expect(
      screen.getAllByText("FACTS_PARTIAL_SUPPORT").length,
    ).toBeGreaterThan(0);
    // A missing signal is called out, not papered over.
    expect(screen.getByText(/with no recorded result/)).toBeInTheDocument();
  });

  it("renders UNVERIFIED status without inventing a score", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency(
          [
            trust(
              "UNVERIFIED",
              [],
              [
                {
                  category: "output",
                  present: false,
                  status: "missing",
                  reason_code: "NO_SIGNALS",
                  detail: "No recorded signals.",
                },
              ],
            ),
          ],
          CROSS_CONSISTENT,
        ),
      }),
    );
    render(<TrustCockpit job={{ ...JOB, source_id: null }} outputs={[]} />);

    await waitFor(() =>
      expect(screen.getByText("UNVERIFIED")).toBeInTheDocument(),
    );
    expect(screen.queryByText(/\d+\.?\d*%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+\.?\d*% safe/)).not.toBeInTheDocument();
    expect(screen.queryByText(/99\.8/)).not.toBeInTheDocument();
  });

  it("never fabricates a trust percentage, accuracy claim or blockchain claim", async () => {
    mockFetch.mockImplementation(
      handler({ consistency: consistency(FACT_STATUSES(), CROSS_CONSISTENT) }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary-1", "summary", {
            integrity: { status: "recorded", digest: "ab12", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() => expect(screen.getByText("TRUSTED")).toBeInTheDocument());
    expect(screen.queryByText(/\d+\.?\d*%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/blockchain/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/100% accurate/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/hallucination-free/i)).not.toBeInTheDocument();
  });
});

describe("TrustCockpit — cross-output consistency", () => {
  it("shows CONSISTENT with the completed-output count", async () => {
    mockFetch.mockImplementation(
      handler({ consistency: consistency([], CROSS_CONSISTENT) }),
    );
    render(<TrustCockpit job={JOB} outputs={[]} />);

    await waitFor(() =>
      expect(
        screen.getByText("Consistent across 2 completed outputs."),
      ).toBeInTheDocument(),
    );
  });

  it("shows INCONSISTENT with bounded conflict details", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency([], {
          status: "INCONSISTENT",
          completed_output_count: 2,
          conflicts: [
            {
              category: "numeric",
              value_a: "$1.2B",
              value_b: "$1.4B",
              output_a_id: "a",
              output_a_type: "summary",
              output_b_id: "b",
              output_b_type: "linkedin",
              message: "Conflict in revenue figure.",
            },
          ],
          checked_pairs: 1,
          note: "",
        }),
      }),
    );
    render(<TrustCockpit job={JOB} outputs={[]} />);

    await waitFor(() =>
      expect(
        screen.getByText("1 conflict detected across completed outputs."),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/numeric · summary \$1\.2B vs linkedin \$1\.4B/),
    ).toBeInTheDocument();
  });

  it("shows NOT_APPLICABLE when fewer than two outputs are completed", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency([], {
          status: "NOT_APPLICABLE",
          completed_output_count: 1,
          conflicts: [],
          checked_pairs: 0,
          note: "",
        }),
      }),
    );
    render(<TrustCockpit job={JOB} outputs={[]} />);

    await waitFor(() =>
      expect(
        screen.getByText(
          "Not applicable — requires at least two completed outputs.",
        ),
      ).toBeInTheDocument(),
    );
  });

  it("keeps consistency UNAVAILABLE (not success) when the endpoint fails", async () => {
    mockFetch.mockImplementation(handler({ consistency: "error" }));
    render(<TrustCockpit job={JOB} outputs={[]} />);

    await waitFor(() =>
      expect(
        screen.getByText("Cross-output consistency is unavailable."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Trust status could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("CONSISTENT")).not.toBeInTheDocument();
  });
});

describe("TrustCockpit — fact verification", () => {
  it("offers on-demand verification per completed output", async () => {
    mockFetch.mockImplementation(handler());
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
          output("out-linkedin", "linkedin", {
            integrity: { status: "recorded", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() =>
      expect(screen.getByText("Fact verification")).toBeInTheDocument(),
    );
    expect(
      screen.getAllByRole("button", { name: "Verify facts" }),
    ).toHaveLength(2);
    // Honest framing — a check that has not run is not a judgement.
    expect(
      screen.getByText(/A check that has not run is not a judgement/),
    ).toBeInTheDocument();
  });

  it("shows a report after a check runs, distinguishing performed vs not", async () => {
    mockFetch.mockImplementation(handler());
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Verify facts" }),
      ).toBeInTheDocument(),
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Verify facts" }),
    );

    await waitFor(() =>
      expect(screen.getByText("SUPPORTED")).toBeInTheDocument(),
    );
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(
      screen.getByText("Claims are supported by project sources."),
    ).toBeInTheDocument();
  });

  it("shows an explicit message when no outputs completed to verify", async () => {
    mockFetch.mockImplementation(handler());
    render(<TrustCockpit job={JOB} outputs={[]} />);

    await waitFor(() =>
      expect(
        screen.getByText(
          "No completed outputs — there is nothing to verify yet.",
        ),
      ).toBeInTheDocument(),
    );
  });
});

describe("TrustCockpit — security signals", () => {
  it("shows real WARNING security signals from source metadata, never a blanket pass", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency([], CROSS_CONSISTENT),
        source: {
          id: "src-1",
          project_id: "proj-1",
          source_type: "file",
          original_filename: "brief.txt",
          storage_key: "k",
          mime_type: "text/plain",
          file_size: 2048,
          language: "en",
          status: "ready",
          source_metadata: {
            malware_scan: { status: "infected", scanner: "clamav" },
            pii_scan: { detected: true, counts: { email: 1 } },
          },
          created_at: "2025-01-01T00:00:00Z",
        },
        securityEvents: {
          success: true,
          count: 1,
          data: [
            {
              id: "evt-1",
              event_type: "malware_detected",
              severity: "high",
              source_id: "src-1",
              created_at: "2025-01-01T00:00:00Z",
            },
          ],
        },
      }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Malware-like content was flagged and recorded/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Personally identifiable information was detected/),
    ).toBeInTheDocument();
    // Infected malware surfaces as WARNING (the scan never claims PASSED).
    expect(screen.getAllByText("WARNING").length).toBeGreaterThanOrEqual(2);
    // No raw PII contents are ever revealed by the pipeline.
    expect(screen.queryByText(/example\.com/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/@/)).not.toBeInTheDocument();
  });

  it("keeps missing source scans UNAVAILABLE/NOT_APPLICABLE, never green", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency([], CROSS_CONSISTENT),
        source: {
          id: "src-1",
          project_id: "proj-1",
          source_type: "file",
          original_filename: "brief.txt",
          storage_key: "k",
          mime_type: "text/plain",
          file_size: 2048,
          language: "en",
          status: "ready",
          source_metadata: null,
          created_at: "2025-01-01T00:00:00Z",
        },
      }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-summary", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
        ]}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/Malware scanning is not enabled in this deployment/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/No PII scan result is recorded on this source/),
    ).toBeInTheDocument();
  });
});

describe("TrustCockpit — artifact integrity", () => {
  it("shows VERIFIED / ERROR / UNAVAILABLE states per artifact", async () => {
    mockFetch.mockImplementation(handler());
    const outputs = [
      output("out-a", "summary", {
        integrity: {
          status: "recorded",
          digest: "abcdef0123456789abcdef0123456789",
          recorded: true,
        },
      }),
      output("out-b", "linkedin", {
        integrity: { status: "tampered", digest: "00" },
      }),
      output("out-c", "advisory", {}),
    ];
    render(<TrustCockpit job={JOB} outputs={outputs} />);

    const section = await screen
      .findByText("Artifact integrity & provenance")
      .then((el) => el.closest("section")!);
    await waitFor(() =>
      expect(within(section).getByText("VERIFIED")).toBeInTheDocument(),
    );
    expect(within(section).getByText("ERROR")).toBeInTheDocument();
    expect(
      within(section).getAllByText("UNAVAILABLE").length,
    ).toBeGreaterThan(0);
    // Truncated fingerprint, never a fabricated ledger claim.
    expect(
      within(section).getByText(/abcdef0123456789…23456789/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/ledger VERIFIED/i)).not.toBeInTheDocument();
  });

  it("says integrity is unavailable for failed outputs with no artifact", async () => {
    mockFetch.mockImplementation(handler());
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-a", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
          output("out-b", "video", { status: "failed" }),
        ]}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/1 failed output produced no artifact/),
      ).toBeInTheDocument(),
    );
  });
});

describe("TrustCockpit — what remains unverified", () => {
  it("lists only real gaps and never claims everything is verified", async () => {
    mockFetch.mockImplementation(handler());
    render(
      <TrustCockpit
        job={{ ...JOB, source_id: null }}
        outputs={[output("out-a", "summary", {})]}
      />,
    );

    await waitFor(() =>
      expect(
        screen.getByText(/No source attached — source-grounded checks/),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/No per-output trust assessment was recorded/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Artifact integrity is unverified for 1 completed output/,
      ),
    ).toBeInTheDocument();
  });

  it("never claims a full-clear while the verification signals have gaps", async () => {
    mockFetch.mockImplementation(
      handler({
        consistency: consistency(ALL_RECORDED_STATUSES(), CROSS_CONSISTENT),
      }),
    );
    render(
      <TrustCockpit
        job={JOB}
        outputs={[
          output("out-a", "summary", {
            integrity: { status: "recorded", recorded: true },
          }),
        ]}
      />,
    );

    // Wait for the consistency fetch to resolve before asserting on the
    // post-load unverified list.
    await waitFor(() =>
      expect(screen.getByText("TRUSTED")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Source is attached — source checks are reported/),
    ).toBeInTheDocument();
    // The on-demand fact check has not run, so a full clear would be a lie.
    expect(
      screen.getByText(/Fact verification has not been run/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/No per-output trust assessment was recorded/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Artifact integrity is unverified/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Nothing unverified stands out/),
    ).not.toBeInTheDocument();
  });
});

describe("trustCounts", () => {
  it("aggregates TRUSTED / CAUTION / UNVERIFIED correctly", () => {
    expect(trustCounts(FACT_STATUSES())).toEqual({
      trusted: 1,
      caution: 1,
      unverified: 0,
    });
    expect(trustCounts([])).toEqual({ trusted: 0, caution: 0, unverified: 0 });
  });
});