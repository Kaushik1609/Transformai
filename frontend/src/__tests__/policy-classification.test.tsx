/**
 * Phase 2A & 2B frontend unit tests — Information classification & policy posture.
 *
 * Covers:
 * - getSourceClassification fallback and resolution
 * - getPolicyPosture mapping
 * - CurrentSource rendering of classification and policy posture badges
 */
import { render, screen } from "@testing-library/react";
import {
  getSourceClassification,
  getPolicyPosture,
  type SourceResponse,
} from "@/lib/api";
import { CurrentSource } from "@/components/upload/CurrentSource";

describe("Phase 2A & 2B — Policy classification helpers", () => {
  const baseSource: SourceResponse = {
    id: "s1",
    project_id: "p1",
    source_type: "text",
    original_filename: "sample.txt",
    storage_key: null,
    mime_type: "text/plain",
    file_size: 1024,
    language: "en",
    status: "ready",
    source_metadata: null,
    created_at: "2026-01-01T00:00:00Z",
  };

  it("resolves legacy unclassified source safely to INTERNAL default", () => {
    expect(getSourceClassification(baseSource)).toBe("INTERNAL");
  });

  it("resolves classification from source_metadata if present", () => {
    const confidentialSource: SourceResponse = {
      ...baseSource,
      source_metadata: { classification: "CONFIDENTIAL" },
    };
    expect(getSourceClassification(confidentialSource)).toBe("CONFIDENTIAL");
  });

  it("resolves classification from top-level classification field if present", () => {
    const restrictedSource: SourceResponse = {
      ...baseSource,
      classification: "RESTRICTED",
    };
    expect(getSourceClassification(restrictedSource)).toBe("RESTRICTED");
  });

  it("returns correct policy posture strings for each classification", () => {
    expect(getPolicyPosture("PUBLIC")).toBe("Cloud Allowed");
    expect(getPolicyPosture("INTERNAL")).toBe("Controlled Processing");
    expect(getPolicyPosture("CONFIDENTIAL")).toBe("Private / Local Required");
    expect(getPolicyPosture("RESTRICTED")).toBe("Private / Local Required (Cloud Denied)");
  });
});

describe("Phase 2A & 2B — CurrentSource UI rendering", () => {
  it("renders CONFIDENTIAL classification badge and policy posture", () => {
    const source: SourceResponse = {
      id: "s2",
      project_id: "p1",
      source_type: "text",
      original_filename: "sensitive_brief.txt",
      storage_key: null,
      mime_type: "text/plain",
      file_size: 2048,
      language: "en",
      status: "ready",
      source_metadata: { classification: "CONFIDENTIAL" },
      created_at: "2026-01-01T00:00:00Z",
    };

    render(<CurrentSource source={source} />);

    expect(screen.getAllByText("CONFIDENTIAL").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Private / Local Required")).toBeInTheDocument();
  });

  it("renders RESTRICTED classification badge and policy posture", () => {
    const source: SourceResponse = {
      id: "s3",
      project_id: "p1",
      source_type: "file",
      original_filename: "top_intel.pdf",
      storage_key: null,
      mime_type: "application/pdf",
      file_size: 4096,
      language: "en",
      status: "ready",
      source_metadata: { classification: "RESTRICTED" },
      created_at: "2026-01-01T00:00:00Z",
    };

    render(<CurrentSource source={source} />);

    expect(screen.getAllByText("RESTRICTED").length).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByText("Private / Local Required (Cloud Denied)"),
    ).toBeInTheDocument();
  });
});
