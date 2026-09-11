/**
 * Phase 12D-B tests — Trust status readout.
 */
import { render, screen } from "@testing-library/react";
import { TrustStatus } from "@/components/verification";
import type { TrustStatusResponse } from "@/lib/api";

const trusted: TrustStatusResponse = {
  status: "TRUSTED",
  reason_codes: [
    "VERIFICATION_PASSED",
    "GROUNDING_STRONG",
    "SECURITY_VALID",
    "INTEGRITY_RECORDED",
    "FACTS_ALL_SUPPORTED",
  ],
  signals: [
    {
      category: "grounding",
      present: true,
      status: "positive",
      reason_code: "GROUNDING_STRONG",
      detail: "Grounding score 0.92 with passed verification.",
    },
    {
      category: "security",
      present: true,
      status: "positive",
      reason_code: "SECURITY_VALID",
      detail: "Output passed L5 security validation.",
    },
    {
      category: "integrity",
      present: true,
      status: "positive",
      reason_code: "INTEGRITY_RECORDED",
      detail: "Artifact integrity was recorded on the ledger.",
    },
    {
      category: "fact_verification",
      present: true,
      status: "positive",
      reason_code: "FACTS_ALL_SUPPORTED",
      detail: "All 3 claims supported by source evidence.",
    },
  ],
  output_id: "o1",
  output_type: "summary",
};

const caution: TrustStatusResponse = {
  ...trusted,
  status: "CAUTION",
  reason_codes: ["FACTS_PARTIAL_SUPPORT"],
  signals: [
    {
      category: "fact_verification",
      present: true,
      status: "warning",
      reason_code: "FACTS_PARTIAL_SUPPORT",
      detail: "2 of 3 claims supported; 1 unverified.",
    },
  ],
};

describe("TrustStatus", () => {
  it("renders status, reason codes and readable signal categories", () => {
    render(<TrustStatus trust={trusted} />);

    expect(screen.getByText("TRUSTED")).toBeInTheDocument();
    expect(screen.getByText("summary")).toBeInTheDocument();
    expect(screen.getByText("GROUNDING_STRONG")).toBeInTheDocument();
    expect(screen.getByText("Grounding")).toBeInTheDocument();
    expect(screen.getByText("Fact verification")).toBeInTheDocument();
    expect(screen.getByText("Integrity")).toBeInTheDocument();
    expect(screen.getByText("Output security")).toBeInTheDocument();
  });

  it("renders a caution status with its warning signal", () => {
    render(<TrustStatus trust={caution} />);
    expect(screen.getByText("CAUTION")).toBeInTheDocument();
    expect(screen.getByText("FACTS_PARTIAL_SUPPORT")).toBeInTheDocument();
    expect(
      screen.getByText(/2 of 3 claims supported/),
    ).toBeInTheDocument();
  });
});