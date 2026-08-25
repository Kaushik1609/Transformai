/**
 * Phase 0 smoke tests — Frontend utility functions.
 *
 * Tests the cn() utility which is foundational to all shadcn/ui components.
 */
import { cn } from "@/lib/utils";

describe("cn (className utility)", () => {
  it("combines class names", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("handles conditional classes", () => {
    expect(cn("base", false && "excluded", "included")).toBe("base included");
  });

  it("merges conflicting Tailwind classes (tailwind-merge)", () => {
    // tailwind-merge should keep only the last conflicting class
    expect(cn("p-4", "p-8")).toBe("p-8");
  });

  it("handles undefined and null gracefully", () => {
    expect(cn("base", undefined, null, "end")).toBe("base end");
  });

  it("handles empty input", () => {
    expect(cn()).toBe("");
  });
});
