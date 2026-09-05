/**
 * Phase 11I-1 — Auth gate hardening tests.
 *
 * Verifies that the application gate trusts ONLY:
 *   1. a valid (non-expired) access token, or
 *   2. a development session when NEXT_PUBLIC_DEV_AUTH_BYPASS is explicitly
 *      true.
 *
 * Also verifies the login page performs the real OTP/JWT flow (verifyOtp →
 * setAuthToken with expiry) and never silently falls back to a dev session.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as authModule from "@/lib/auth";
import { authApi, type AuthTokenResponse } from "@/lib/api";
import { RequireAuth } from "@/components/auth";
import LoginPage from "@/app/login/page";

const push = jest.fn();
const replace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

jest.mock("@/lib/api", () => ({
  authApi: {
    login: jest.fn(),
    verifyOtp: jest.fn(),
  },
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const mockLogin = authApi.login as jest.Mock;
const mockVerifyOtp = authApi.verifyOtp as jest.Mock;

function otpDelivery() {
  return {
    success: true,
    data: {
      channel: "email",
      identifier: "dev@transformiq.local",
      resend_after_seconds: 30,
    },
    message: "Verification code sent.",
  };
}

function tokenResponse(): AuthTokenResponse {
  return {
    success: true,
    access_token: "jwt-token-123",
    token_type: "bearer",
    expires_in: 3600,
    user: {
      id: "user-1",
      email: "dev@transformiq.local",
      name: "Dev User",
      role: "operator",
    },
  };
}

beforeEach(() => {
  localStorage.clear();
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
  push.mockClear();
  replace.mockClear();
  mockLogin.mockReset();
  mockVerifyOtp.mockReset();
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
  jest.restoreAllMocks();
});

describe("RequireAuth — access-token gating", () => {
  it("renders protected content when a valid, non-expired token is present", async () => {
    authModule.setAuthToken("jwt-valid", Date.now() + 60_000);

    render(<RequireAuth>protected content</RequireAuth>);

    await waitFor(() =>
      expect(screen.getByText("protected content")).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("redirects to /login when no token is present and dev bypass is unset", async () => {
    render(<RequireAuth>protected content</RequireAuth>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("redirects to /login when the token is expired and clears the stale token", async () => {
    authModule.setAuthToken("jwt-stale", Date.now() - 1000);
    const clearSpy = jest.spyOn(authModule, "clearAuthToken");

    render(<RequireAuth>protected content</RequireAuth>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(clearSpy).toHaveBeenCalled();
    expect(authModule.getAuthToken()).toBeNull();
    expect(localStorage.getItem(authModule.AUTH_STORE_KEY)).toBeNull();
  });

  it("does NOT allow access via a dev session alone when the bypass flag is unset", async () => {
    authModule.setDevSession("dev@transformiq.local");

    render(<RequireAuth>protected content</RequireAuth>);

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("allows access via a dev session ONLY when the bypass flag is explicitly true", async () => {
    authModule.setDevSession("dev@transformiq.local");
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";

    render(<RequireAuth>protected content</RequireAuth>);

    await waitFor(() =>
      expect(screen.getByText("protected content")).toBeInTheDocument(),
    );
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("LoginPage — real OTP/JWT flow", () => {
  it("signs in via verifyOtp, stores the token with its expiry, and never opens a dev session", async () => {
    mockLogin.mockResolvedValue(otpDelivery());
    mockVerifyOtp.mockResolvedValue(tokenResponse());
    const setAuthTokenSpy = jest.spyOn(authModule, "setAuthToken");
    const setDevSessionSpy = jest.spyOn(authModule, "setDevSession");

    render(<LoginPage />);
    await userEvent.type(
      screen.getByLabelText("Email"),
      "dev@transformiq.local",
    );
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(mockLogin).toHaveBeenCalledWith({ email: "dev@transformiq.local" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Verification code")).toBeInTheDocument(),
    );

    await userEvent.type(screen.getByLabelText("Verification code"), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Verify code" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(mockVerifyOtp).toHaveBeenCalledWith({
      email: "dev@transformiq.local",
      otp: "123456",
    });
    expect(setAuthTokenSpy).toHaveBeenCalledWith("jwt-token-123", expect.any(Number));
    expect(setDevSessionSpy).not.toHaveBeenCalled();
    expect(authModule.getAuthToken()).toBe("jwt-token-123");
  });

  it("shows an inline error on failed verification and does not store a token", async () => {
    mockLogin.mockResolvedValue(otpDelivery());
    mockVerifyOtp.mockRejectedValue(new Error("Incorrect code"));
    const setAuthTokenSpy = jest.spyOn(authModule, "setAuthToken");

    render(<LoginPage />);
    await userEvent.type(
      screen.getByLabelText("Email"),
      "dev@transformiq.local",
    );
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(screen.getByLabelText("Verification code")).toBeInTheDocument(),
    );

    await userEvent.type(screen.getByLabelText("Verification code"), "000000");
    await userEvent.click(screen.getByRole("button", { name: "Verify code" }));

    await waitFor(() =>
      expect(
        screen.getByText(
          "The verification code is incorrect or has expired. Please try again.",
        ),
      ).toBeInTheDocument(),
    );
    expect(setAuthTokenSpy).not.toHaveBeenCalled();
    expect(authModule.getAuthToken()).toBeNull();
    expect(replace).not.toHaveBeenCalledWith("/");
  });
});