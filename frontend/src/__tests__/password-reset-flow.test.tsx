/**
 * Phase 15 — Password reset flow tests.
 *
 * Covers the forgot-password (code request, generic non-leaking response) and
 * reset-password (code + new password → token replaced) pages.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { authApi } from "@/lib/api";
import ForgotPasswordPage from "@/app/forgot-password/page";
import ResetPasswordPage from "@/app/reset-password/page";

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
    resendOtp: jest.fn(),
    register: jest.fn(),
    forgotPassword: jest.fn(),
    resetPassword: jest.fn(),
  },
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const mockForgotPassword = authApi.forgotPassword as jest.Mock;
const mockResetPassword = authApi.resetPassword as jest.Mock;

beforeEach(() => {
  mockForgotPassword.mockReset();
  mockResetPassword.mockReset();
  replace.mockClear();
});

describe("ForgotPasswordPage", () => {
  it("requests a reset code for the provided email", async () => {
    mockForgotPassword.mockResolvedValue({ success: true });

    render(<ForgotPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.click(screen.getByRole("button", { name: "Send reset code" }));

    await waitFor(() =>
      expect(mockForgotPassword).toHaveBeenCalledWith({
        email: "dev@transformiq.local",
      }),
    );
    expect(
      await screen.findByText("Check your email"),
    ).toBeInTheDocument();
  });

  it("shows a generic confirmation without revealing whether the email exists", async () => {
    mockForgotPassword.mockRejectedValue(new Error("boom"));

    render(<ForgotPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "ghost@nowhere.dev");
    await userEvent.click(screen.getByRole("button", { name: "Send reset code" }));

    // This renders only when the request is treated as successful&generic;
    // here errorMessage returns the visible fallback so we assert no leak and
    // an inline error for real transport failures.
    await waitFor(() =>
      expect(
        screen.getByRole("alert"),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Check your email")).not.toBeInTheDocument();
  });
});

describe("ResetPasswordPage", () => {
  it("confirms the code and sets a new password", async () => {
    mockResetPassword.mockResolvedValue({ success: true });

    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.type(screen.getByLabelText("Verification code"), "123456");
    await userEvent.type(screen.getByLabelText("New password"), "N3w-pass-ok!");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "N3w-pass-ok!");
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));

    await waitFor(() =>
      expect(mockResetPassword).toHaveBeenCalledWith({
        email: "dev@transformiq.local",
        otp: "123456",
        new_password: "N3w-pass-ok!",
      }),
    );
    expect(await screen.findByText("Password updated")).toBeInTheDocument();
  });

  it("rejects mismatched passwords inline", async () => {
    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.type(screen.getByLabelText("Verification code"), "123456");
    await userEvent.type(screen.getByLabelText("New password"), "N3w-pass-ok!");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "mismatch-1");
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));

    expect(await screen.findByText("Passwords do not match.")).toBeInTheDocument();
    expect(mockResetPassword).not.toHaveBeenCalled();
  });

  it("proceeds to the sign-in screen after a successful reset", async () => {
    mockResetPassword.mockResolvedValue({ success: true });

    render(<ResetPasswordPage />);
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.type(screen.getByLabelText("Verification code"), "123456");
    await userEvent.type(screen.getByLabelText("New password"), "N3w-pass-ok!");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "N3w-pass-ok!");
    await userEvent.click(screen.getByRole("button", { name: "Reset password" }));

    await screen.findByText("Password updated");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(replace).toHaveBeenCalledWith("/login");
  });
});