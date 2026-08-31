/**
 * Tests the cn() utility which is foundational to all shadcn/ui components,
 * plus the copyText() clipboard helper used by the Phase 10 copy buttons.
 */
import { cn, copyText } from "@/lib/utils";

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

describe("copyText (clipboard helper)", () => {
  const mockExecCommand = (value: boolean): jest.Mock => {
    const execCommand = jest.fn().mockReturnValue(value);
    Object.defineProperty(document, "execCommand", {
      value: execCommand,
      configurable: true,
    });
    return execCommand;
  };

  it("uses the Clipboard API when available", async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    const execCommand = mockExecCommand(true);

    await expect(copyText("hello")).resolves.toBe(true);
    expect(writeText).toHaveBeenCalledWith("hello");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("falls back to execCommand when the Clipboard API is missing", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    const execCommand = mockExecCommand(true);

    await expect(copyText("legacy")).resolves.toBe(true);
    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("returns false when copying fails or input is empty", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    mockExecCommand(false);

    await expect(copyText("nope")).resolves.toBe(false);
    await expect(copyText("")).resolves.toBe(false);
  });
});
