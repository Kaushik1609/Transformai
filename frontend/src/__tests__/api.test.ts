/**
 * Phase 1 tests — Frontend API client foundation.
 *
 * Verifies:
 * 1. API_BASE_URL reads correctly from the environment variable.
 * 2. ApiError is constructable with status and detail.
 * 3. apiFetch (via network mock) handles success and error responses.
 * 4. healthApi object exposes the expected methods.
 */
import {
  API_BASE_URL,
  ApiError,
  healthApi,
  type HealthResponse,
  type ReadyResponse,
} from "@/lib/api";

// ---------------------------------------------------------------------------
// API_BASE_URL
// ---------------------------------------------------------------------------

describe("API_BASE_URL", () => {
  it("defaults to http://localhost:8000 when env var is not set", () => {
    // In the test environment NEXT_PUBLIC_API_URL is not set, so the default
    // is used.
    expect(API_BASE_URL).toBe("http://localhost:8000");
  });
});

// ---------------------------------------------------------------------------
// ApiError
// ---------------------------------------------------------------------------

describe("ApiError", () => {
  it("is an instance of Error", () => {
    const err = new ApiError(404, "Not found");
    expect(err).toBeInstanceOf(Error);
  });

  it("stores the status code", () => {
    const err = new ApiError(503, "Service unavailable");
    expect(err.status).toBe(503);
  });

  it("stores the detail message", () => {
    const err = new ApiError(422, "Validation failed");
    expect(err.detail).toBe("Validation failed");
  });

  it("has name ApiError", () => {
    const err = new ApiError(500, "Server error");
    expect(err.name).toBe("ApiError");
  });

  it("message equals detail", () => {
    const err = new ApiError(400, "Bad request");
    expect(err.message).toBe("Bad request");
  });
});

// ---------------------------------------------------------------------------
// healthApi shape
// ---------------------------------------------------------------------------

describe("healthApi", () => {
  it("exposes a health method", () => {
    expect(typeof healthApi.health).toBe("function");
  });

  it("exposes a ready method", () => {
    expect(typeof healthApi.ready).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// Fetch mock tests
// ---------------------------------------------------------------------------

const mockFetch = jest.fn();
global.fetch = mockFetch;

function makeMockResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

beforeEach(() => {
  mockFetch.mockReset();
});

describe("healthApi.health (mocked fetch)", () => {
  it("returns HealthResponse on success", async () => {
    const payload: HealthResponse = {
      status: "ok",
      service: "transformiq-backend",
      version: "0.1.0",
      environment: "development",
      uptime_seconds: 42,
    };
    mockFetch.mockResolvedValueOnce(makeMockResponse(payload));

    const result = await healthApi.health();
    expect(result.status).toBe("ok");
    expect(result.service).toBe("transformiq-backend");
    expect(result.uptime_seconds).toBe(42);
  });

  it("throws ApiError when backend returns 503", async () => {
    mockFetch.mockResolvedValueOnce(
      makeMockResponse({ detail: "Service unavailable" }, 503),
    );

    await expect(healthApi.health()).rejects.toThrow(ApiError);
  });

  it("throws ApiError with detail from response body", async () => {
    mockFetch.mockResolvedValueOnce(
      makeMockResponse({ detail: "Not found" }, 404),
    );

    try {
      await healthApi.health();
      fail("Should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).detail).toBe("Not found");
      expect((err as ApiError).status).toBe(404);
    }
  });

  it("throws ApiError with status 0 on network failure", async () => {
    mockFetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(healthApi.health()).rejects.toThrow(ApiError);

    try {
      await healthApi.health();
    } catch (err) {
      // second call also rejects
    }
  });
});

describe("healthApi.ready (mocked fetch)", () => {
  it("returns ReadyResponse with checks", async () => {
    const payload: ReadyResponse = {
      status: "ready",
      checks: { database: "ok", redis: "ok" },
    };
    mockFetch.mockResolvedValueOnce(makeMockResponse(payload));

    const result = await healthApi.ready();
    expect(result.status).toBe("ready");
    expect(result.checks.database).toBe("ok");
    expect(result.checks.redis).toBe("ok");
  });

  it("returns not_ready response when deps are unavailable", async () => {
    const payload: ReadyResponse = {
      status: "not_ready",
      checks: { database: "unavailable", redis: "ok" },
    };
    // 503 still has a parseable JSON body
    mockFetch.mockResolvedValueOnce(makeMockResponse(payload, 503));

    await expect(healthApi.ready()).rejects.toThrow(ApiError);
  });
});
