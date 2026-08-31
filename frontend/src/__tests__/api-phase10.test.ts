/**
 * Phase 10 tests — output history + export client methods and error mapping.
 *
 * Verifies:
 * 1. transformationsApi.listByProject hits the project history endpoint and
 *    returns the job list.
 * 2. outputsApi.export POSTs to the export endpoint with the requested format
 *    and returns the parsed blob/filename.
 * 3. errorMessage maps 5xx/network errors to a friendly fallback while keeping
 *    meaningful client/validation details.
 */
import { outputsApi, transformationsApi, ApiError, errorMessage } from "@/lib/api";
import { blobResponse, jsonResponse } from "./helpers";

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("transformationsApi.listByProject", () => {
  it("requests the project transformations endpoint", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          success: true,
          data: [
            {
              id: "j2",
              project_id: "p1",
              requested_outputs: { output_types: ["summary"] },
              status: "completed",
              progress: 100,
              error_message: null,
              started_at: "2025-01-02T00:00:00Z",
              completed_at: "2025-01-02T00:02:00Z",
              created_at: "2025-01-02T00:00:00Z",
            },
          ],
          count: 1,
        },
        200,
      ),
    );

    const res = await transformationsApi.listByProject("p1");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/transformations");
    expect(init?.method).toBeUndefined(); // JSON GET, no explicit method
    expect(res.count).toBe(1);
    expect(res.data[0].id).toBe("j2");
  });

  it("throws ApiError with detail on failure", async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ detail: "Project not found" }, 404),
    );
    await transformationsApi.listByProject("missing").catch((err: unknown) => {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.detail).toBe("Project not found");
    });
  });
});

describe("outputsApi.export", () => {
  it("POSTs the export endpoint with the format query and returns bytes", async () => {
    mockFetch.mockResolvedValueOnce(
      blobResponse(new Blob(["PK-mock"], { type: "application/vnd..." }), 200, {
        "content-disposition": 'attachment; filename="summary.docx"',
      }),
    );

    const result = await outputsApi.export("o1", "docx");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/outputs/o1/export?format=docx");
    expect(init?.method).toBe("POST");
    expect(result.filename).toBe("summary.docx");
    expect(result.blob).toBeInstanceOf(Blob);
  });

  it("defaults to pdf format when requested", async () => {
    mockFetch.mockResolvedValueOnce(blobResponse(new Blob(), 200));
    await outputsApi.export("o2", "pdf");
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/api/v1/outputs/o2/export?format=pdf");
  });

  it("throws ApiError on 409 while the output is still generating", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Output o1 is still generating." }),
    } as unknown as Response);

    await outputsApi.export("o1", "pdf").catch((err: unknown) => {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(409);
    });
  });

  it("throws ApiError with status 0 on network failure", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(outputsApi.export("o1", "pdf")).rejects.toBeInstanceOf(
      ApiError,
    );
  });
});

describe("errorMessage", () => {
  it("returns the fallback for network failures (status 0)", () => {
    expect(errorMessage(new ApiError(0, "Network error: x"), "fallback")).toBe(
      "fallback",
    );
  });

  it("returns the fallback for 5xx server errors", () => {
    expect(errorMessage(new ApiError(500, "Internal Server Error"), "fallback")).toBe(
      "fallback",
    );
  });

  it("keeps client and validation detail messages", () => {
    expect(errorMessage(new ApiError(404, "Project not found"), "fallback")).toBe(
      "Project not found",
    );
    expect(errorMessage(new ApiError(422, "Invalid format"), "fallback")).toBe(
      "Invalid format",
    );
  });

  it("falls back to the default for empty detail and unknown errors", () => {
    expect(errorMessage(new ApiError(400, ""), "fallback")).toBe("fallback");
    expect(errorMessage(new Error("boom"), "fallback")).toBe("fallback");
    expect(errorMessage(undefined, "fallback")).toBe("fallback");
  });
});