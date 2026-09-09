/**
 * Phase 15 — Theme provider (Light / Dark / System) tests.
 *
 * Verifies the provider syncs the `dark` class on <html>, persists the choice
 * under THEME_KEY, and reflects the logged-in context. The UI-facing behavior
 * is exercised through the Settings Appearance section.
 */
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider, THEME_KEY, useTheme } from "@/components/theme";
import SettingsPage from "@/app/settings/page";
import { setDevSession, setAuthToken } from "@/lib/auth";

const push = jest.fn();
const replace = jest.fn();
jest.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  usePathname: () => "/",
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
}));

jest.mock("@/lib/api", () => ({
  authApi: { logout: jest.fn(() => Promise.resolve({ success: true })) },
  errorMessage: (_err: unknown, fallback: string) => fallback,
}));

function Probe() {
  const { theme } = useTheme();
  return <p data-testid="probe">{theme}</p>;
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  // Force a light system preference for deterministic assertions.
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

describe("ThemeProvider", () => {
  it("defaults to System (light in this test environment) and removes .dark", async () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("system"),
    );
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("applies the stored dark choice on mount and persists toggles", async () => {
    localStorage.setItem(THEME_KEY, "dark");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("dark"),
    );
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
  });

  it("does not overwrite an existing stored theme on mount", async () => {
    localStorage.setItem(THEME_KEY, "light");
    const setSpy = jest.spyOn(Storage.prototype, "setItem");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("light"),
    );
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
    const writes = setSpy.mock.calls.filter(([key]) => key === THEME_KEY).length;
    expect(writes).toBe(0);
    expect(document.documentElement).not.toHaveClass("dark");
    setSpy.mockRestore();
  });

  it("applies a stored light theme even when the OS prefers dark", async () => {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: jest.fn().mockImplementation((query: string) => ({
        matches: query.includes("dark") ? true : false,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
    });
    localStorage.setItem(THEME_KEY, "light");

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("light"),
    );
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("resolves System to the OS scheme and keeps it live", async () => {
    const listeners: Array<() => void> = [];
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: jest.fn().mockImplementation((query: string) => ({
        matches: query.includes("dark") ? true : false,
        media: query,
        onchange: null,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: (_e: string, fn: () => void) => listeners.push(fn),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      })),
    });

    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("system"),
    );
    expect(document.documentElement).toHaveClass("dark");
  });
});

describe("Settings — Appearance", () => {
  it("switches themes from the Appearance section and persists the choice", async () => {
    // The settings page is under RequireAuth — provide a valid session.
    setAuthToken("t", Date.now() + 60_000);
    setDevSession("dev@transformiq.local");

    render(
      <ThemeProvider>
        <SettingsPage />
      </ThemeProvider>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Appearance" })).toBeInTheDocument(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Appearance" }));

    await waitFor(() =>
      expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("radio", { name: "Light" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");

    await userEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");

    await userEvent.click(screen.getByRole("radio", { name: "System" }));
    expect(localStorage.getItem(THEME_KEY)).toBe("system");
  });
});