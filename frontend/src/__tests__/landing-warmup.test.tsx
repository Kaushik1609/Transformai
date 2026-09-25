/**
 * KaryaSetu AI — Landing Page Backend Warm-Up Tests.
 *
 * Verifies:
 * 1. LandingPage triggers the non-blocking /health request on mount.
 * 2. Request uses NEXT_PUBLIC_API_URL when configured.
 * 3. Request falls back gracefully when NEXT_PUBLIC_API_URL is unset.
 * 4. Request is completely non-blocking and never renders spinners or errors.
 * 5. Failed requests (network errors, 502/503 sleeping backend) do not break the page.
 * 6. No authentication headers or tokens are attached.
 * 7. Deduplication avoids redundant requests across repeated mounts in a session.
 */

import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { LandingPage } from "@/components/landing";
import { warmupBackend, _resetWarmupForTesting, healthApi } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";

// Mock ArchitectureDemo to avoid jsdom audio element pause warnings
jest.mock("@/components/demo/ArchitectureDemo", () => ({
  ArchitectureDemo: () => <div data-testid="architecture-demo-mock" />,
}));

function makeMockResponse(body: unknown = { status: "ok" }, status = 200): any {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

describe("Frontend Backend Warm-Up", () => {
  const originalEnv = process.env.NEXT_PUBLIC_API_URL;
  const originalFetch = global.fetch;
  let mockFetch: jest.Mock;

  beforeEach(() => {
    _resetWarmupForTesting();
    sessionStorage.clear();
    mockFetch = jest.fn().mockImplementation(() =>
      Promise.resolve(makeMockResponse({ status: "ok" }, 200))
    );
    global.fetch = mockFetch;
    if (typeof window !== "undefined") {
      (window as any).fetch = mockFetch;
    }
  });

  afterEach(() => {
    global.fetch = originalFetch;
    if (typeof window !== "undefined") {
      (window as any).fetch = originalFetch;
    }
    if (originalEnv !== undefined) {
      process.env.NEXT_PUBLIC_API_URL = originalEnv;
    } else {
      delete process.env.NEXT_PUBLIC_API_URL;
    }
    _resetWarmupForTesting();
    sessionStorage.clear();
  });

  it("triggers a GET /health request when LandingPage mounts", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://karyasetu-api.onrender.com";

    render(<LandingPage />);

    expect(screen.getAllByText("KaryaSetu AI")[0]).toBeInTheDocument();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    const [calledUrl, options] = mockFetch.mock.calls[0];
    expect(calledUrl).toBe("https://karyasetu-api.onrender.com/health");
    expect(options?.method).toBe("GET");
  });

  it("correctly handles trailing slashes in NEXT_PUBLIC_API_URL", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://karyasetu-api.onrender.com/";

    render(<LandingPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toBe("https://karyasetu-api.onrender.com/health");
  });

  it("falls back gracefully when NEXT_PUBLIC_API_URL is unset", async () => {
    delete process.env.NEXT_PUBLIC_API_URL;

    render(<LandingPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    const [calledUrl] = mockFetch.mock.calls[0];
    expect(calledUrl).toMatch(/\/health$/);
  });

  it("is non-blocking and does not show loading spinner or error UI", async () => {
    // Simulate a slow sleeping backend taking time to respond
    mockFetch.mockImplementation(
      () =>
        new Promise((resolve) => {
          setTimeout(
            () => resolve(makeMockResponse({ status: "ok" }, 200)),
            200
          );
        })
    );

    render(<LandingPage />);

    // Landing page elements must be immediately visible without waiting for fetch
    expect(
      screen.getByRole("heading", { name: /One trusted source/i })
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Create account/i })[0]
    ).toBeInTheDocument();

    // No spinner or alert should ever appear for the warm-up
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("silently handles network rejection without breaking the landing page", async () => {
    mockFetch.mockImplementation(() =>
      Promise.reject(new Error("Failed to fetch — backend sleeping"))
    );

    expect(() => {
      render(<LandingPage />);
    }).not.toThrow();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    // Content remains fully rendered and functional
    expect(
      screen.getByRole("heading", { name: /One trusted source/i })
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("silently handles 502/503 HTTP responses without breaking the landing page", async () => {
    mockFetch.mockImplementation(() =>
      Promise.resolve(
        makeMockResponse({ detail: "Bad Gateway / Cold Start" }, 502)
      )
    );

    render(<LandingPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    expect(
      screen.getByRole("heading", { name: /One trusted source/i })
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("does not attach auth headers and preserves unauthenticated state", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://karyasetu-api.onrender.com";

    render(<LandingPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    const [, options] = mockFetch.mock.calls[0];
    expect(options?.headers).toBeUndefined();
    expect(getAuthToken()).toBeNull();
  });

  it("prevents duplicate warm-up requests within the same browser session", async () => {
    process.env.NEXT_PUBLIC_API_URL = "https://karyasetu-api.onrender.com";

    // First mount
    const { unmount } = render(<LandingPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(1);
    });

    unmount();

    // Second mount in same session
    render(<LandingPage />);

    // Should NOT call fetch again because warm-up already ran
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });

  it("exposes warmup function on healthApi object", () => {
    expect(typeof healthApi.warmup).toBe("function");
    expect(healthApi.warmup).toBe(warmupBackend);
  });
});
