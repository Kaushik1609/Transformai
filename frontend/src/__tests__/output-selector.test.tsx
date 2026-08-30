/**
 * Phase 9 tests — Output selector.
 *
 * Verifies toggle selection against the backend's supported output types and
 * the selection count surfaced to the parent.
 *
 * Note: the checkbox's accessible name includes the description (e.g.
 * "Executive Summary — Concise, decision-ready overview…"), so queries use
 * partial regex matches on the label.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OutputSelector } from "@/components/output-selection";
import { OUTPUT_TYPES } from "@/lib/outputTypes";

const checkbox = (label: string) =>
  screen.getByRole("checkbox", { name: new RegExp(label) });

describe("OutputSelector", () => {
  it("renders every supported output type with its label", () => {
    render(<OutputSelector selected={[]} onChange={jest.fn()} />);
    for (const { label } of OUTPUT_TYPES) {
      expect(checkbox(label)).toBeInTheDocument();
    }
  });

  it("reports checks as they are toggled", async () => {
    const onChange = jest.fn();
    render(<OutputSelector selected={["summary"]} onChange={onChange} />);

    const summary = checkbox("Executive Summary");
    expect(summary).toHaveAttribute("aria-checked", "true");

    await userEvent.click(summary);
    expect(onChange).toHaveBeenLastCalledWith([]);

    const video = checkbox("Video");
    await userEvent.click(video);
    expect(onChange).toHaveBeenLastCalledWith(["summary", "video"]);
  });

  it("respects visual selection state", () => {
    render(<OutputSelector selected={["infographic"]} onChange={jest.fn()} />);
    expect(checkbox("Infographic")).toHaveAttribute("aria-checked", "true");
    expect(checkbox("LinkedIn Post")).toHaveAttribute("aria-checked", "false");
  });

  it("does nothing while disabled", async () => {
    const onChange = jest.fn();
    render(<OutputSelector selected={[]} onChange={onChange} disabled />);
    await userEvent.click(checkbox("Advisory"));
    expect(onChange).not.toHaveBeenCalled();
  });
});