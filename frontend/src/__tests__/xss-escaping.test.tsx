/**
 * Phase 11H tests — client-side XSS escaping of generated output.
 *
 * Generated/source content arriving via the API must always render as inert
 * text. React escapes every interpolated string, and ResultsPanel never uses
 * dangerouslySetInnerHTML, so hostile markdown/HTML arriving inside
 * text_content or structured_content must stay inert: no <script>, <iframe>,
 * <img>, or <a href> nodes can exist in the rendered DOM.
 */
import { render, screen } from "@testing-library/react";
import { ResultsPanel } from "@/components/results";
import type { OutputResponse } from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const createOutput = (overrides: Partial<OutputResponse>): OutputResponse => ({
  id: "o1",
  job_id: "j1",
  output_type: "summary",
  status: "completed",
  structured_content: null,
  storage_key: null,
  mime_type: null,
  text_content: null,
  output_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  mockFetch.mockReset();
  // VerificationPanel fetches for each completed output.
  mockFetch.mockResolvedValue(jsonResponse({ success: true, data: [], count: 0 }));
});

describe("ResultsPanel XSS escaping", () => {
  it("escapes script/iframe/event-handler payloads in text_content", () => {
    const hostile =
      "<script>alert(1)</script><iframe src=x></iframe>" +
      "<img src=x onerror=alert(2)> and <a href='javascript:alert(3)'>linktext</a>";
    const { container } = render(
      <ResultsPanel
        outputs={[createOutput({ id: "s", text_content: hostile })]}
      />,
    );

    // The hostile source is still visible as inert text...
    expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
    // ...but produced no executable DOM elements and no URL attributes.
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a[href]")).toBeNull();
    expect(container.querySelector("[onerror]")).toBeNull();
  });

  it("escapes hostile structured thread posts", () => {
    const { container } = render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "x",
            output_type: "x",
            structured_content: {
              thread: [
                "<script>alert(1)</script>",
                "<img src=x onerror=alert(2)>",
                "plain post",
              ],
            },
          }),
        ]}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("plain post")).toBeInTheDocument();
  });

  it("escapes hostile slide titles and key messages", () => {
    const { container } = render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "p",
            output_type: "presentation",
            structured_content: {
              title: "<script>bad()</script>",
              slides: [
                {
                  title: "<img src=x onerror=alert(1)>",
                  key_message: "<iframe src=x></iframe>",
                },
              ],
            },
          }),
        ]}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("iframe")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText(/Slide 1/)).toBeInTheDocument();
  });

  it("escapes hostile failure messages", () => {
    const { container } = render(
      <ResultsPanel
        outputs={[
          createOutput({
            id: "f",
            output_type: "advisory",
            status: "failed",
            output_metadata: {
              error_message: "<script>alert(1)</script>",
              failed_at: "2025-01-01T00:00:00Z",
            },
          }),
        ]}
      />,
    );
    expect(container.querySelector("script")).toBeNull();
  });
});