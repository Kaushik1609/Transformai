/**
 * UI-8 / a11y tests — dialog & drawer keyboard / focus behaviour.
 *
 * The app's hand-rolled dialogs and the mobile drawer are hardened with the
 * shared modal-a11y behaviour: focus moves into the dialog when it opens,
 * the body scroll is locked while it is open, Escape closes it, and focus
 * returns to the trigger afterwards.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ProjectsPage from "@/app/projects/page";
import { jsonResponse, type FetchMock } from "./helpers";
import { setDevSession } from "@/lib/auth";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
  useSearchParams: () => ({ get: () => null }),
  useParams: () => ({}),
  usePathname: () => "/projects",
}));

beforeEach(() => {
  mockFetch.mockReset();
  mockFetch.mockResolvedValue(
    jsonResponse({ success: true, data: [], count: 0 }),
  );
  localStorage.clear();
  process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS = "true";
  setDevSession("dev@transformiq.local");
  document.body.style.overflow = "";
});

afterEach(() => {
  delete (process.env as Record<string, string | undefined>)
    .NEXT_PUBLIC_DEV_AUTH_BYPASS;
  document.body.style.overflow = "";
});

async function openCreateProjectModal(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getAllByRole("button", { name: /Create Project/ })[0]);
  return await screen.findByRole("dialog", { name: /create project/i });
}

describe("Modal a11y — create project dialog", () => {
  it("moves focus into the dialog, locks scroll, and closes on Escape", async () => {
    const user = userEvent.setup();
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());

    const openButton = screen.getAllByRole("button", { name: /Create Project/ })[0];
    const dialog = await openCreateProjectModal(user);

    // Focus has moved inside the dialog and body scroll is locked.
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    // Escape closes the dialog, restores scroll, and returns focus.
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(openButton);
  });

  it("keeps focus inside the dialog while tabbing", async () => {
    const user = userEvent.setup();
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());

    const dialog = await openCreateProjectModal(user);
    for (let i = 0; i < 8; i += 1) {
      await user.tab();
      expect(dialog.contains(document.activeElement)).toBe(true);
    }
  });
});

describe("Modal a11y — mobile navigation drawer", () => {
  it("focuses the drawer, closes on Escape and returns focus to the toggle", async () => {
    const user = userEvent.setup();
    render(<ProjectsPage />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());

    const toggle = screen.getByRole("button", { name: "Open navigation" });
    await user.click(toggle);

    const drawer = await screen.findByRole("dialog", { name: /navigation/i });
    expect(drawer.contains(document.activeElement)).toBe(true);
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: /navigation/i })).not.toBeInTheDocument(),
    );
    expect(document.body.style.overflow).toBe("");
    expect(document.activeElement).toBe(toggle);
  });
});