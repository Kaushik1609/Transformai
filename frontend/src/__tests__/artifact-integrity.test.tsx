/**
 * Phase 12D-F tests — Artifact integrity & provenance readout.
 */
import { render, screen } from "@testing-library/react";
import { ArtifactIntegrity } from "@/components/verification";
import type { OutputResponse } from "@/lib/api";

function output(
  output_metadata: Record<string, unknown> | null,
): OutputResponse {
  return {
    id: "o1",
    job_id: "job",
    output_type: "summary",
    status: "completed",
    structured_content: null,
    text_content: "Body",
    storage_key: "sum.txt",
    mime_type: "text/plain",
    output_metadata,
    created_at: "2025-01-01T00:00:00Z",
  };
}

const DIGEST =
  "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08";

describe("ArtifactIntegrity", () => {
  it("renders VERIFIED with a truncated fingerprint when recorded and provenance RECORDED", () => {
    render(
      <ArtifactIntegrity
        compact={false}
        output={output({
          integrity: {
            status: "recorded",
            recorded: true,
            algorithm: "sha256",
            digest: DIGEST,
            reference: "j:ledger",
            provider: "ledger",
          },
        })}
      />,
    );

    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("RECORDED")).toBeInTheDocument();
    const fingerprint = screen.getByText(new RegExp(DIGEST.slice(0, 16)));
    expect(fingerprint).toBeInTheDocument();
  });

  it("notes PROVENANCE UNAVAILABLE when recorded-true is absent", () => {
    render(
      <ArtifactIntegrity
        compact={false}
        output={output({
          integrity: {
            status: "local",
            digest: DIGEST,
            reference: "self-hash",
          },
        })}
      />,
    );
    expect(screen.getByText("VERIFIED")).toBeInTheDocument();
    expect(screen.getByText("UNAVAILABLE")).toBeInTheDocument();
  });

  it("renders ERROR when the artifact no longer matches its digest", () => {
    render(
      <ArtifactIntegrity
        compact={false}
        output={output({
          integrity: { status: "tampered", digest: DIGEST },
        })}
      />,
    );
    expect(screen.getByText("ERROR")).toBeInTheDocument();
  });

  it("renders a compact badge without the full provenance detail", () => {
    render(
      <ArtifactIntegrity
        compact
        output={output({
          integrity: { status: "tampered", digest: DIGEST },
        })}
      />,
    );
    expect(screen.getByText(/Integrity · ERROR/)).toBeInTheDocument();
  });
});