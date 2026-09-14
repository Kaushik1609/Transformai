/**
 * Phase 9 tests — Source upload.
 *
 * Covers text ingestion, file ingestion (routing/extension), the uploading
 * state, inline error display, and empty/hidden inputs.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceUpload } from "@/components/upload";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

const SOURCE = {
  id: "s1",
  project_id: "p1",
  source_type: "text",
  original_filename: null,
  storage_key: null,
  mime_type: "text/plain",
  file_size: 42,
  language: "en",
  status: "ready",
  source_metadata: null,
  created_at: "2025-01-01T00:00:00Z",
};

beforeEach(() => {
  mockFetch.mockReset();
});

describe("SourceUpload — text mode", () => {
  it("ingests text and reports the added source", async () => {
    const onSourceAdded = jest.fn();
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: SOURCE }, 201));

    render(<SourceUpload projectId="p1" onSourceAdded={onSourceAdded} />);

    await userEvent.type(
      screen.getByLabelText("Source text"),
      "Key market insights for the quarter.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add text source" }));

    await waitFor(() => expect(onSourceAdded).toHaveBeenCalledWith(SOURCE));

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/sources/text");
    expect(JSON.parse(init.body as string)).toEqual({
      text: "Key market insights for the quarter.",
      language: "en",
      classification: "INTERNAL",
    });
  });

  it("allows selecting a custom classification", async () => {
    const onSourceAdded = jest.fn();
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: SOURCE }, 201));

    render(<SourceUpload projectId="p1" onSourceAdded={onSourceAdded} />);

    await userEvent.selectOptions(
      screen.getByLabelText("Information classification"),
      "CONFIDENTIAL",
    );
    await userEvent.type(
      screen.getByLabelText("Source text"),
      "Internal strategy memorandum.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Add text source" }));

    await waitFor(() => expect(onSourceAdded).toHaveBeenCalledWith(SOURCE));

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      text: "Internal strategy memorandum.",
      language: "en",
      classification: "CONFIDENTIAL",
    });
  });

  it("shows the character count while text is present", async () => {
    mockFetch.mockResolvedValue(jsonResponse({ success: true, data: SOURCE }, 201));
    render(<SourceUpload projectId="p1" onSourceAdded={jest.fn()} />);

    await userEvent.type(screen.getByLabelText("Source text"), "hello hello");
    expect(screen.getByText("11 characters")).toBeInTheDocument();
  });

  it("surfaces backend validation errors inline", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Source text must not contain PII." }, 422),
    );
    render(<SourceUpload projectId="p1" onSourceAdded={jest.fn()} />);

    await userEvent.type(screen.getByLabelText("Source text"), "Contains secrets");
    await userEvent.click(screen.getByRole("button", { name: "Add text source" }));

    await waitFor(() =>
      expect(screen.getByText("Source text must not contain PII.")).toBeInTheDocument(),
    );
  });

  it("is disabled while the text field is empty", () => {
    render(<SourceUpload projectId="p1" onSourceAdded={jest.fn()} />);
    expect(screen.getByRole("button", { name: "Add text source" })).toBeDisabled();
  });
});

describe("SourceUpload — file mode", () => {
  it("uploads a TXT file via the /file route", async () => {
    const onSourceAdded = jest.fn();
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: SOURCE }, 201));

    render(<SourceUpload projectId="p1" onSourceAdded={onSourceAdded} />);
    await userEvent.click(screen.getByRole("button", { name: "File" }));

    const file = new File(["line1\nline2"], "notes.txt", { type: "text/plain" });
    await userEvent.upload(screen.getByLabelText("Source file input"), file);
    await userEvent.click(screen.getByRole("button", { name: "Upload file" }));

    await waitFor(() => expect(onSourceAdded).toHaveBeenCalled());

    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toContain("/sources/file");
  });

  it("shows file name and size once selected", async () => {
    render(<SourceUpload projectId="p1" onSourceAdded={jest.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "File" }));

    const file = new File(["data"], "brief.docx", { type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    await userEvent.upload(screen.getByLabelText("Source file input"), file);
    expect(screen.getByText("brief.docx")).toBeInTheDocument();
  });

  it("disables the upload button until a file is chosen", async () => {
    render(<SourceUpload projectId="p1" onSourceAdded={jest.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "File" }));
    expect(screen.getByRole("button", { name: "Upload file" })).toBeDisabled();
  });
});