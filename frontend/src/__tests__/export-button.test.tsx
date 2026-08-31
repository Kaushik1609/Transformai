/**
 * Phase 10 tests — Document export button.
 *
 * Verifies the button POSTs to the export endpoint, triggers a browser
 * download of the returned bytes, and surfaces server-side errors inline.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportButton } from "@/components/export";
import { blobResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

afterAll(() => {
  jest.restoreAllMocks();
});

describe("ExportButton", () => {
  it("posts to the export endpoint and downloads the returned docx", async () => {
    const createObjectURL = jest.fn(() => "blob:mock-export");
    const revokeObjectURL = jest.fn();
    const anchorClick = jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    window.URL.createObjectURL =
      createObjectURL as unknown as typeof URL.createObjectURL;
    window.URL.revokeObjectURL =
      revokeObjectURL as unknown as typeof URL.revokeObjectURL;

    mockFetch.mockResolvedValueOnce(
      blobResponse(new Blob(["PK-mock"], { type: "application/vnd..." }), 200, {
        "content-disposition": 'attachment; filename="summary.docx"',
      }),
    );

    render(<ExportButton outputId="o1" format="docx" />);
    await userEvent.click(screen.getByRole("button", { name: "DOCX" }));

    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/outputs/o1/export?format=docx");
    expect(init?.method).toBe("POST");
    expect(anchorClick).toHaveBeenCalled();
    expect(revokeObjectURL).toHaveBeenCalled();
    anchorClick.mockRestore();
  });

  it("requests a pdf export when format is pdf", async () => {
    mockFetch.mockResolvedValueOnce(blobResponse(new Blob(), 200));
    render(<ExportButton outputId="o2" format="pdf" />);
    await userEvent.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/api/v1/outputs/o2/export?format=pdf");
  });

  it("surfaces export errors inline (e.g. output still generating)", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Output o1 is still generating." }),
    } as unknown as Response);

    render(<ExportButton outputId="o1" format="pdf" />);
    await userEvent.click(screen.getByRole("button", { name: "PDF" }));

    expect(
      await screen.findByText("Output o1 is still generating."),
    ).toBeInTheDocument();
  });
});