/**
 * Phase 9 tests — Download button (basic export via Phase 8E endpoint).
 *
 * Verifies artifact option derivation from output metadata and that clicking
 * triggers a browser download of the blob returned by the API.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DownloadButton, artifactOptions } from "@/components/export";
import type { OutputResponse } from "@/lib/api";
import { blobResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const createOutput = (overrides: Partial<OutputResponse>): OutputResponse => ({
  id: "o1",
  job_id: "j1",
  output_type: "summary",
  status: "completed",
  structured_content: null,
  storage_key: "sum/summary.txt",
  mime_type: "text/plain",
  text_content: "Summary text",
  output_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
  ...overrides,
});

beforeEach(() => {
  mockFetch.mockReset();
});

afterAll(() => {
  jest.restoreAllMocks();
});

describe("artifactOptions", () => {
  it("exposes the primary artifact when storage exists", () => {
    const opts = artifactOptions(createOutput({}));
    expect(opts.map((o) => o.role)).toEqual(["primary"]);
    expect(opts[0].label).toBe("TXT");
  });

  it("adds a PDF companion for infographics", () => {
    const opts = artifactOptions(
      createOutput({
        output_type: "infographic",
        mime_type: "image/png",
        output_metadata: {
          artifact: "infographic",
          pdf_storage_key: "inf/summary.pdf",
        },
      }),
    );
    expect(opts.map((o) => o.role)).toEqual(["primary", "pdf"]);
    expect(opts[0].label).toBe("PNG");
  });

  it("adds an SRT companion for videos", () => {
    const opts = artifactOptions(
      createOutput({
        output_type: "video",
        output_metadata: {
          artifact: "video",
          subtitle_storage_key: "vid/captions.srt",
        },
      }),
    );
    expect(opts.map((o) => o.role)).toEqual(["primary", "srt"]);
  });

  it("returns an empty list when no artifact is stored", () => {
    const opts = artifactOptions(
      createOutput({ storage_key: null, mime_type: null }),
    );
    expect(opts).toEqual([]);
  });

  it("labels presentations as PPTX", () => {
    const opts = artifactOptions(
      createOutput({
        output_type: "presentation",
        mime_type:
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      }),
    );
    expect(opts[0].label).toBe("PPTX");
  });
});

describe("DownloadButton", () => {
  it("renders nothing when there is no artifact", () => {
    const { container } = render(
      <DownloadButton
        output={createOutput({ storage_key: null, mime_type: null })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("downloads the blob and triggers a browser download", async () => {
    const createObjectURL = jest.fn(() => "blob:mock-url");
    const revokeObjectURL = jest.fn();
    const anchorClick = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    window.URL.createObjectURL = createObjectURL as unknown as typeof URL.createObjectURL;
    window.URL.revokeObjectURL = revokeObjectURL as unknown as typeof URL.revokeObjectURL;

    const output = createOutput({});
    mockFetch.mockResolvedValueOnce(
      blobResponse(new Blob(["summary"], { type: "text/plain" }), 200, {
        "content-disposition": 'attachment; filename="summary.txt"',
      }),
    );

    render(<DownloadButton output={output} />);

    await userEvent.click(screen.getByRole("button", { name: "TXT" }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/api/v1/outputs/o1/download?artifact=primary");
    expect(anchorClick).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
    anchorClick.mockRestore();
  });

  it("surfaces download errors inline (e.g. artifact still generating)", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Output o1 is still generating." }),
    } as unknown as Response);

    render(
      <DownloadButton
        output={createOutput({})}
        label="Download Executive Summary"
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Download Executive Summary (TXT)" }),
    );

    await waitFor(() =>
      expect(
        screen.getByText("Output o1 is still generating."),
      ).toBeInTheDocument(),
    );
  });
});