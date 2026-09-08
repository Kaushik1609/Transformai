/**
 * Auth / account-flow tests — OTP/JWT flow + dev-bypass gateway.
 *
 * Covers login, register, login↔register navigation, the application-session
 * gate (unauthenticated → /login, authenticated → shell), and logout.
 *
 * The development-session paths here run ONLY with
 * NEXT_PUBLIC_DEV_AUTH_BYPASS=true (the gated, explicit development path);
 * the real OTP/JWT flow is covered in require-auth-token.test.tsx.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "@/app/login/page";
import RegisterPage from "@/app/register/page";
import { AppShell } from "@/components/layout";
import {
  getDevSession,
  setDevSession,
  clearDevSession,
  isDevAuthBypassEnabled,
} from "@/lib/auth";

const push = jest.fn();
const replace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

beforeEach(() => {
  localStorage.clear();
  clearDevSession();
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
  push.mockClear();
  replace.mockClear();
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
});

describe("LoginPage", () => {
  it("renders the sign-in form and brand", () => {
    render(<LoginPage />);
    expect(screen.getByText("Welcome back")).toBeInTheDocument();
    expect(screen.getByText(/One source/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("blocks submission with empty fields", async () => {
    render(<LoginPage />);
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(
      screen.getByText("Please enter your email and password."),
    ).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("starts a development session (dev bypass enabled) and proceeds to the app after valid submit", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(getDevSession()?.email).toBe("dev@transformiq.local");
  });

  it("links to the register page", () => {
    render(<LoginPage />);
    const link = screen.getByRole("link", { name: "Create account" });
    expect(link).toHaveAttribute("href", "/register");
  });
});

describe("auth module contract (regression: named export must stay callable)", () => {
  it("exports isDevAuthBypassEnabled as a function returning a boolean", () => {
    expect(typeof isDevAuthBypassEnabled).toBe("function");
    expect(typeof isDevAuthBypassEnabled()).toBe("boolean");
  });

  it("is false when NEXT_PUBLIC_DEV_AUTH_BYPASS is unset and true when 'true'", () => {
    delete (process.env as Record<string, string | undefined>)
      .NEXT_PUBLIC_DEV_AUTH_BYPASS;
    expect(isDevAuthBypassEnabled()).toBe(false);
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    expect(isDevAuthBypassEnabled()).toBe(true);
  });
});

describe("RegisterPage", () => {
  it("renders the registration form and brand", () => {
    render(<RegisterPage />);
    expect(screen.getByText("Create your account")).toBeInTheDocument();
    expect(screen.getByText(/One source/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByLabelText("Confirm password")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create account" }),
    ).toBeInTheDocument();
  });

  it("blocks registration when passwords do not match", async () => {
    render(<RegisterPage />);
    await userEvent.type(screen.getByLabelText("Name"), "Dev User");
    await userEvent.type(screen.getByLabelText("Email"), "dev@transformiq.local");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.type(screen.getByLabelText("Confirm password"), "different");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(screen.getByText("Passwords do not match.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
    expect(getDevSession()).toBeNull();
  });

  it("starts a development session (dev bypass enabled) and proceeds to the app after valid submit", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    render(<RegisterPage />);
    await userEvent.type(screen.getByLabelText("Name"), "Jane Doe");
    await userEvent.type(screen.getByLabelText("Email"), "jane@transformiq.local");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.type(screen.getByLabelText("Confirm password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
    expect(getDevSession()?.email).toBe("jane@transformiq.local");
    expect(getDevSession()?.name).toBe("Jane Doe");
  });

  it("links back to the login page", () => {
    render(<RegisterPage />);
    const link = screen.getByRole("link", { name: "Sign in" });
    expect(link).toHaveAttribute("href", "/login");
  });
});

describe("application session gate", () => {
  it("redirects unauthenticated users to /login and hides the shell", async () => {
    render(<AppShell>app content</AppShell>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(screen.queryByRole("link", { name: "Projects" })).not.toBeInTheDocument();
    expect(screen.queryByText("app content")).not.toBeInTheDocument();
  });

  it("renders the authenticated application for a development session (dev bypass enabled)", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    setDevSession("dev@transformiq.local");
    render(<AppShell>app content</AppShell>);
    await waitFor(() =>
      expect(screen.getByText("app content")).toBeInTheDocument(),
    );
    expect(screen.getByRole("link", { name: "Projects" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "History" })).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("logs out from the profile menu and returns to /login", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    setDevSession("dev@transformiq.local", "Dev User");
    localStorage.setItem("transformiq.quick_project_id", "quick-1");
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ success: true }),
    }) as unknown as typeof fetch;
    render(<AppShell>app content</AppShell>);
    await waitFor(() =>
      expect(screen.getByText("app content")).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Account menu" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Log out" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
    expect(getDevSession()).toBeNull();
    expect(localStorage.getItem("transformiq.quick_project_id")).toBeNull();
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/auth/logout"),
      expect.objectContaining({ method: "POST" }),
    );
  });
});