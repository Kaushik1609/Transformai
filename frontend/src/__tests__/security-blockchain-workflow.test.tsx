import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { SecurityBlockchainWorkflow } from "@/components/auth";

describe("SecurityBlockchainWorkflow Component", () => {
  it("renders the canvas and all 5 security & provenance nodes", () => {
    render(<SecurityBlockchainWorkflow />);

    expect(screen.getByText("Source Ingest")).toBeInTheDocument();
    expect(screen.getAllByText("Zero-Trust Gate").length).toBeGreaterThan(0);
    expect(screen.getByText("Policy Enclave")).toBeInTheDocument();
    expect(screen.getAllByText(/Integrity & Provenance/).length).toBeGreaterThan(0);
    expect(screen.getByText("Cryptographic Seal")).toBeInTheDocument();
  });

  it("renders badges along the curved connection lines", () => {
    render(<SecurityBlockchainWorkflow />);

    expect(screen.getAllByText("SHA-256 Digest").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Zero-Trust").length).toBeGreaterThan(0);
    expect(screen.getByText("Integrity Anchor")).toBeInTheDocument();
    expect(screen.getByText("Integrity Seal")).toBeInTheDocument();
    expect(screen.getByText("Grounding Link")).toBeInTheDocument();
  });

  it("renders security & provenance focus callouts at the bottom", () => {
    render(<SecurityBlockchainWorkflow />);

    expect(screen.getAllByText("Zero-Trust").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Integrity").length).toBeGreaterThan(0);
    expect(screen.getByText("Provenance")).toBeInTheDocument();
    expect(screen.getAllByText("SHA-256 · Ed25519").length).toBeGreaterThan(0);
    expect(screen.getByText("Fail-Closed Gate")).toBeInTheDocument();
  });

  it("updates micro-detail pane when a node is clicked", () => {
    render(<SecurityBlockchainWorkflow />);

    // Click on Zero-Trust Gate node
    const zeroTrustNode = screen.getByRole("button", { name: "Zero-Trust Gate" });
    fireEvent.click(zeroTrustNode);

    expect(screen.getAllByText("Zero-Trust Gate").length).toBe(2);
    expect(
      screen.getByText(/Deterministic PII masking & fail-closed malware filter/)
    ).toBeInTheDocument();
  });
});
