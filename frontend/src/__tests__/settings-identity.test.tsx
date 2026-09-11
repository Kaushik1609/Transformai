/**
 * Phase 15 — Settings account identity tests.
 *
 * The Account section must show the real authenticated user (persisted by
 * password login), never a hardcoded development persona. The development
 * identity is shown ONLY as an explicit fallback when the development bypass
 * is active, and a stale dev session must never surface for a real account.
 */
import { render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider } from "@/components/theme";
import SettingsPage from "@/app/settings/page";
import { setDevSession, setAuthToken, setAuthUser, AUTH_USER_KEY } from "@/lib/auth";

const push = jest.fn();
const replace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/settings",
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

jest.mock("@/lib/api", () => ({
  authApi: { logout: jest.fn(() => Promise.resolve({ success: true })) },
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

const REAL_USER = {
  id: "user-100",
  email: "analyst@transformiq.example",
  name: "Real Analyst",
  role: "operator",
};

function renderSettings() {
  setAuthToken("jwt-test", Date.now() + 60_000);
  return render(
    <ThemeProvider>
      <SettingsPage />
    </ThemeProvider>,
  );
}

function realAccountParagraph() {
  return screen.getByText("This is the account you are signed in with.");
}

beforeEach(() => {
  localStorage.clear();
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
  replace.mockClear();
  push.mockClear();
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: jest.fn().mockImplementation((query: string) => ({
      matches: query.includes("dark") ? false : true,
      media: query,
      onchange: null,
      addListener: jest.fn(),
      removeListener: jest.fn(),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
      dispatchEvent: jest.fn(),
    })),
  });
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
});

describe("Settings — Account identity", () => {
  it("shows the real authenticated user and no development persona", async () => {
    setAuthUser(REAL_USER);
    renderSettings();

    await waitFor(() => expect(realAccountParagraph()).toBeInTheDocument());
    expect(screen.getByLabelText("Name")).toHaveValue("Real Analyst");
    expect(screen.getByLabelText("Email")).toHaveValue(
      "analyst@transformiq.example",
    );
    expect(screen.queryByText("Dev User")).not.toBeInTheDocument();
    expect(screen.queryByText("dev@transformiq.local")).not.toBeInTheDocument();
  });

  it("shows the development identity only when the bypass is active", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
    setDevSession("dev@transformiq.local", "Dev User");
    renderSettings();

    await waitFor(() =>
      expect(
        screen.getByText(
          "Your account is currently using the explicit development identity (dev mode).",
        ),
      ).toBeInTheDocument(),
    );
    expect(screen.getByLabelText("Name")).toHaveValue("Dev User");
    expect(screen.getByLabelText("Email")).toHaveValue("dev@transformiq.local");
  });

  it("never presents a stale dev session to a real account", async () => {
    setAuthUser(REAL_USER);
    setDevSession("dev@transformiq.local", "Dev User");
    renderSettings();

    await waitFor(() => expect(realAccountParagraph()).toBeInTheDocument());
    expect(screen.getByLabelText("Name")).toHaveValue("Real Analyst");
    expect(screen.getByLabelText("Email")).toHaveValue(
      "analyst@transformiq.example",
    );
    expect(screen.queryByText("Dev User")).not.toBeInTheDocument();
    expect(localStorage.getItem(AUTH_USER_KEY)).not.toBeNull();
  });

  it("does not invent a development identity for a token without a stored user", async () => {
    setDevSession("dev@transformiq.local", "Dev User");
    renderSettings();

    await waitFor(() => expect(realAccountParagraph()).toBeInTheDocument());
    expect(screen.getByLabelText("Name")).toHaveValue("Signed in");
    expect(screen.queryByText("Dev User")).not.toBeInTheDocument();
  });
});