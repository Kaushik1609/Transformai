/**
 * Phase 9 tests — Output type registry and status helpers.
 */
import {
  OUTPUT_TYPES,
  outputTypeLabel,
  jobStatusVariant,
  outputStatusVariant,
  sourceStatusVariant,
  verificationStatusVariant,
  isTerminalJobStatus,
  isTerminalOutputStatus,
  formatFileSize,
  formatDateTime,
} from "@/lib/outputTypes";

describe("OUTPUT_TYPES", () => {
  it("mirrors the backend's supported output types exactly", () => {
    const ids = OUTPUT_TYPES.map((t) => t.id).sort();
    expect(ids).toEqual(
      [
        "summary",
        "linkedin",
        "x",
        "advisory",
        "infographic",
        "presentation",
        "video",
      ].sort(),
    );
  });

  it("exposes human-readable labels", () => {
    expect(outputTypeLabel("summary")).toBe("Executive Summary");
    expect(outputTypeLabel("video")).toBe("Video");
  });

  it("falls back to the raw value for unknown types", () => {
    expect(outputTypeLabel("mystery")).toBe("mystery");
  });
});

describe("status helpers", () => {
  it("maps job statuses to badge variants", () => {
    expect(jobStatusVariant("queued")).toBe("info");
    expect(jobStatusVariant("running")).toBe("info");
    expect(jobStatusVariant("completed")).toBe("success");
    expect(jobStatusVariant("failed")).toBe("error");
    expect(jobStatusVariant("cancelled")).toBe("muted");
    expect(jobStatusVariant("weird")).toBe("default");
  });

  it("maps output statuses to badge variants", () => {
    expect(outputStatusVariant("generating")).toBe("info");
    expect(outputStatusVariant("completed")).toBe("success");
    expect(outputStatusVariant("failed")).toBe("error");
  });

  it("maps source statuses to badge variants", () => {
    expect(sourceStatusVariant("ready")).toBe("success");
    expect(sourceStatusVariant("processing")).toBe("info");
    expect(sourceStatusVariant("uploaded")).toBe("info");
    expect(sourceStatusVariant("failed")).toBe("error");
  });

  it("maps verification statuses to badge variants", () => {
    expect(verificationStatusVariant("success")).toBe("success");
    expect(verificationStatusVariant("warning")).toBe("warning");
    expect(verificationStatusVariant("failed")).toBe("error");
  });
});

describe("terminal status predicates", () => {
  it("treats completed/failed/cancelled as terminal job states", () => {
    expect(isTerminalJobStatus("completed")).toBe(true);
    expect(isTerminalJobStatus("failed")).toBe(true);
    expect(isTerminalJobStatus("cancelled")).toBe(true);
    expect(isTerminalJobStatus("queued")).toBe(false);
    expect(isTerminalJobStatus("running")).toBe(false);
  });

  it("treats completed/failed as terminal output states", () => {
    expect(isTerminalOutputStatus("completed")).toBe(true);
    expect(isTerminalOutputStatus("failed")).toBe(true);
    expect(isTerminalOutputStatus("generating")).toBe(false);
  });
});

describe("formatFileSize", () => {
  it("formats byte sizes", () => {
    expect(formatFileSize(0)).toBe("0 B");
    expect(formatFileSize(1024)).toBe("1 KB");
    expect(formatFileSize(1536)).toBe("1.5 KB");
    expect(formatFileSize(null)).toBe("—");
    expect(formatFileSize(undefined)).toBe("—");
  });
});

describe("formatDateTime", () => {
  it("formats an ISO timestamp", () => {
    const result = formatDateTime("2025-01-01T00:00:00Z");
    expect(result).not.toBe("—");
    expect(result).toContain("2025");
  });

  it("returns an em dash for missing values", () => {
    expect(formatDateTime(null)).toBe("—");
    expect(formatDateTime(undefined)).toBe("—");
    expect(formatDateTime("not-a-date")).toBe("—");
  });
});