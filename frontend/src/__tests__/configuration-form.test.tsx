/**
 * Phase 9 tests — Configuration form.
 *
 * Verifies the audience/tone/language/detail/objective inputs and that the
 * created configuration payload matches the backend contract.
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigurationForm } from "@/components/configuration";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

describe("ConfigurationForm", () => {
  it("saves a configuration with all provided fields", async () => {
    const onConfigCreated = jest.fn();
    const config = {
      id: "c1",
      project_id: "p1",
      target_audience: "technology executives",
      tone: "professional",
      language: "English",
      detail_level: "detailed",
      communication_objective: "decision support",
      content_style: "bullet-points",
      custom_instructions: null,
      created_at: "2025-01-01T00:00:00Z",
    };
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: config }, 201));

    render(<ConfigurationForm projectId="p1" onConfigCreated={onConfigCreated} />);

    await userEvent.type(screen.getByLabelText("Target audience"), "technology executives");
    await userEvent.type(screen.getByLabelText("Tone"), "professional");
    await userEvent.selectOptions(screen.getByLabelText("Detail level"), "detailed");
    await userEvent.type(screen.getByLabelText("Communication objective"), "decision support");
    await userEvent.type(screen.getByLabelText(/Content style/), "bullet-points");
    await userEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await waitFor(() => expect(onConfigCreated).toHaveBeenCalledWith(config));

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/configurations");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({
      target_audience: "technology executives",
      tone: "professional",
      language: "English",
      detail_level: "detailed",
      communication_objective: "decision support",
      content_style: "bullet-points",
      custom_instructions: null,
    });
  });

  it("defaults to English / standard detail level", () => {
    render(<ConfigurationForm projectId="p1" onConfigCreated={jest.fn()} />);
    expect((screen.getByLabelText("Output language") as HTMLInputElement).value).toBe("English");
    expect((screen.getByLabelText("Detail level") as HTMLSelectElement).value).toBe("standard");
  });

  it("surfaces save errors inline", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ detail: "Language is required." }, 422));
    render(<ConfigurationForm projectId="p1" onConfigCreated={jest.fn()} />);

    await userEvent.clear(screen.getByLabelText("Output language"));
    await userEvent.type(screen.getByLabelText("Output language"), "Klingon");
    await userEvent.click(screen.getByRole("button", { name: "Save configuration" }));

    await waitFor(() =>
      expect(screen.getByText("Language is required.")).toBeInTheDocument(),
    );
  });

  it("renders the loading placeholder when disabled", () => {
    render(
      <ConfigurationForm projectId="p1" onConfigCreated={jest.fn()} disabled />,
    );
    expect(screen.getByText("Loading configuration…")).toBeInTheDocument();
  });
});