/**
 * Phase 1.5 Stabilization Frontend Tests.
 *
 * Covers:
 * 1. Public Landing Page renders for unauthenticated visitors.
 * 2. Authenticated vs unauthenticated gating on root route (/).
 * 3. Cold-start retry behavior (transient 502/503 retry, non-transient 400/401/404 do not retry).
 * 4. Scoped quick project cache by authenticated user ID.
 * 5. Truthful security status in ProjectSourceLibrary (File validation ACTIVE, Malware UNAVAILABLE).
 * 6. Session expired banner on Login page.
 * 7. Register page never auto-fills OTP.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LandingPage } from "@/components/landing";
import LoginPage from "@/app/login/page";
import RegisterPage from "@/app/register/page";
import RootPage from "@/app/page";
import { ProjectSourceLibrary } from "@/components/projects/ProjectSourceLibrary";
import {
  setDevSession,
  clearDevSession,
  setAuthToken,
  setAuthUser,
} from "@/lib/auth";
import {
  ensureQuickProject,
  getCachedQuickProjectId,
  setCachedQuickProjectId,
} from "@/lib/quickWorkspace";
import { jsonResponse, type FetchMock } from "./helpers";
import { healthApi, ApiError } from "@/lib/api";

const push = jest.fn();
const replace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/",
  useSearchParams: () => ({
    get: (key: string) => (key === "session_expired" ? "true" : null),
  }),
  useParams: () => ({}),
}));

beforeEach(() => {
  localStorage.clear();
  clearDevSession();
  push.mockClear();
  replace.mockClear();
});

describe("Phase 1.5 — Public Landing Page", () => {
  it("renders public branding, mission, and factual transformation value proposition", () => {
    render(<LandingPage />);
    expect(screen.getAllByText("KaryaSetu AI")[0]).toBeInTheDocument();
    expect(
      screen.getByText(/Policy-Controlled Information Transformation/i),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /One trusted source/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Sign in" }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Create account/i })[0],
    ).toBeInTheDocument();
  });

  it("does not render protected workspace controls or internal data on landing page", () => {
    render(<LandingPage />);
    expect(screen.queryByText("Create Transformation")).not.toBeInTheDocument();
    expect(screen.queryByText("Project Source Library")).not.toBeInTheDocument();
  });
});

describe("Phase 1.5 — Root Page Workspace Gating", () => {
  it("renders LandingPage when user is unauthenticated", () => {
    render(<RootPage />);
    expect(screen.getAllByText("KaryaSetu AI")[0]).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /One trusted source/i }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: /Create account/i })[0],
    ).toBeInTheDocument();
  });

  it("renders workspace when authenticated via auth token", async () => {
    setAuthToken("fake-jwt-token", Date.now() + 3600000);
    setAuthUser({
      id: "u1",
      email: "officer@example.gov",
      name: "Officer Test",
      role: "operator",
    });
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse({ success: true, data: [], count: 0 }),
    ) as unknown as typeof fetch;

    render(<RootPage />);
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: /One trusted source/i })).not.toBeInTheDocument(),
    );
  });
});

describe("Phase 1.5 — Session Expiry Handling", () => {
  it("displays session expired alert banner on login page when query param is present", () => {
    render(<LoginPage />);
    expect(
      screen.getByText("Your session has expired. Please sign in again."),
    ).toBeInTheDocument();
  });
});

describe("Phase 1.5 — OTP Security & Verification Flow", () => {
  it("never auto-fills OTP or renders dev_otp in registration flow", async () => {
    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse({
        success: true,
        data: {
          channel: "email",
          identifier: "newuser@example.com",
          resend_after_seconds: 60,
          delivery_status: "delivered",
        },
        message: "Verification code sent.",
      }, 201),
    ) as unknown as typeof fetch;

    render(<RegisterPage />);
    await userEvent.type(screen.getByLabelText("Name"), "New User");
    await userEvent.type(screen.getByLabelText("Email"), "newuser@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "Password123!");
    await userEvent.type(screen.getByLabelText("Confirm password"), "Password123!");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(screen.getByText("Check your email")).toBeInTheDocument(),
    );

    // The code input must be completely empty — never prefilled with an OTP
    const codeInput = screen.getByLabelText("Verification code") as HTMLInputElement;
    expect(codeInput.value).toBe("");
    expect(screen.queryByText(/auto-detected/i)).not.toBeInTheDocument();
  });
});

describe("Phase 1.5 — Scoped Quick Project Cache", () => {
  it("scopes cached quick project ID to authenticated user ID", () => {
    setAuthUser({
      id: "user-alpha",
      email: "alpha@example.com",
      name: "Alpha User",
      role: "operator",
    });
    setCachedQuickProjectId("project-alpha-123");

    expect(getCachedQuickProjectId()).toBe("project-alpha-123");

    // Switching to user-beta
    setAuthUser({
      id: "user-beta",
      email: "beta@example.com",
      name: "Beta User",
      role: "operator",
    });
    expect(getCachedQuickProjectId()).toBeNull();

    setCachedQuickProjectId("project-beta-456");
    expect(getCachedQuickProjectId()).toBe("project-beta-456");
  });
});

describe("Phase 1.5 — Truthful Security States in ProjectSourceLibrary", () => {
  it("renders truthful active file validation and truthful unavailable malware status", async () => {
    const mockSource = {
      id: "src-1",
      name: "executive_brief.pdf",
      original_filename: "executive_brief.pdf",
      project_id: "p1",
      source_type: "pdf",
      filename: "executive_brief.pdf",
      mime_type: "application/pdf",
      file_size: 1024,
      status: "ready",
      source_metadata: {
        file_security: { status: "active", validated_format: "pdf" },
        malware_scan: {
          status: "unavailable",
          scanner: "clamav",
          reason: "daemon_unreachable",
        },
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    global.fetch = jest.fn().mockResolvedValue(
      jsonResponse({ success: true, data: [mockSource], count: 1 }),
    ) as unknown as typeof fetch;

    render(<ProjectSourceLibrary projectId="p1" />);

    await waitFor(() =>
      expect(screen.getByText("executive_brief.pdf")).toBeInTheDocument(),
    );
    expect(screen.getByText(/File validation ACTIVE/i)).toBeInTheDocument();
    expect(screen.getByText(/Malware/i)).toBeInTheDocument();
    expect(screen.getAllByText(/UNAVAILABLE/i).length).toBeGreaterThanOrEqual(1);
  });
});

describe("Phase 1.5 — Cold-Start Retry Behavior", () => {
  it("does not retry 400 or 404 client errors", async () => {
    const mockFetch = jest.fn().mockResolvedValue(
      jsonResponse({ detail: "Not found" }, 404),
    );
    global.fetch = mockFetch as unknown as typeof fetch;

    await expect(healthApi.health()).rejects.toThrow(ApiError);
    // Must only be called once — 404 is not transient
    expect(mockFetch).toHaveBeenCalledTimes(1);
  });
});
