/**
 * Phase 9 tests — Artifact download / blob handling.
 *
 * Verifies GET /api/v1/outputs/{id}/download returns a Blob, parses the
 * Content-Disposition filename, and converts non-2xx JSON responses
 * (404/409) into ApiError per backend conventions.
 */
import { outputsApi, ApiError } from "@/lib/api";
import { blobResponse } from "./helpers";

const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("outputsApi.download", () => {
  it("requests the primary artifact and returns its blob", async () => {
    mockFetch.mockResolvedValueOnce(
      blobResponse(new Blob(["bytes"], { type: "application/vnd..." }), 200, {
        "content-disposition": 'attachment; filename="presentation.pptx"',
      }),
    );

    const result = await outputsApi.download("o1", "primary");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "http://localhost:8000/api/v1/outputs/o1/download?artifact=primary",
    );
    expect(init).toBeUndefined(); // no auth headers sent in dev mode
    expect(result.filename).toBe("presentation.pptx");
    expect(result.blob).toBeInstanceOf(Blob);
  });

  it("supports the pdf and srt companion roles", async () => {
    mockFetch.mockResolvedValueOnce(blobResponse(new Blob(), 200));
    await outputsApi.download("o1", "pdf");
    expect(mockFetch.mock.calls[0][0]).toContain("artifact=pdf");

    mockFetch.mockResolvedValueOnce(blobResponse(new Blob(), 200));
    await outputsApi.download("o1", "srt");
    expect(mockFetch.mock.calls[1][0]).toContain("artifact=srt");
  });

  it("tolerates a missing content-disposition header", async () => {
    mockFetch.mockResolvedValueOnce(blobResponse(new Blob(), 200));
    const result = await outputsApi.download("o1");
    expect(result.filename).toBeUndefined();
  });

  it("throws ApiError with detail on 404", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Artifact not available for output o1." }),
    } as unknown as Response);

    await expect(outputsApi.download("o1")).rejects.toBeInstanceOf(ApiError);
    await outputsApi.download("o1").catch((err: unknown) => {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(404);
      expect(apiErr.detail).toBe("Artifact not available for output o1.");
    });
  });

  it("throws ApiError on 409 while the output is still generating", async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Output o1 is still generating." }),
    } as unknown as Response);

    await outputsApi.download("o1").catch((err: unknown) => {
      const apiErr = err as ApiError;
      expect(apiErr.status).toBe(409);
      expect(apiErr.detail).toBe("Output o1 is still generating.");
    });
  });

  it("throws ApiError with status 0 on network failure", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(outputsApi.download("o1")).rejects.toBeInstanceOf(ApiError);
  });
});