/**
 * Phase 10 tests — Copy button.
 *
 * Verifies the button copies the given text (via the Clipboard API when
 * available) and falls back to a graceful inline error when copying fails.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CopyButton } from "@/components/export";

describe("CopyButton", () => {
  afterEach(() => {
    jest.restoreAllMocks();
  });

  it("copies the text to the clipboard and confirms", async () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });

    render(<CopyButton text="hello world" />);
    await userEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("hello world"));
    expect(await screen.findByText("Copied!")).toBeInTheDocument();
  });

  it("shows an inline error when copy is unavailable", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: undefined,
      configurable: true,
    });
    // jsdom does not implement document.execCommand; define it so the legacy
    // fallback path runs and reports a failure.
    const execCommand = jest.fn().mockReturnValue(false);
    Object.defineProperty(document, "execCommand", {
      value: execCommand,
      configurable: true,
    });

    render(<CopyButton text="cannot copy" />);
    await userEvent.click(screen.getByRole("button", { name: "Copy to clipboard" }));

    expect(
      await screen.findByText("Copy failed. Select the text and copy manually."),
    ).toBeInTheDocument();
    expect(execCommand).toHaveBeenCalledWith("copy");
  });
});