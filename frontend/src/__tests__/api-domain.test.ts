/**
 * Phase 9 tests — Domain API client methods.
 *
 * Verifies the projects / sources / configurations / transformations /
 * outputs / verification client methods: request paths, bodies, success
 * parsing, and error → ApiError conversion.
 */
import {
  projectsApi,
  sourcesApi,
  configurationsApi,
  transformationsApi,
  outputsApi,
  contentIntelligenceApi,
  ApiError,
  type SourceResponse,
} from "@/lib/api";
import { jsonResponse, type FetchMock } from "./helpers";

const mockFetch = jest.fn() as unknown as FetchMock;
global.fetch = mockFetch;

beforeEach(() => {
  mockFetch.mockReset();
});

async function expectApiError(promise: Promise<unknown>, status: number, detail: string) {
  await expect(promise).rejects.toBeInstanceOf(ApiError);
  await promise.catch((err: unknown) => {
    const apiErr = err as ApiError;
    expect(apiErr.status).toBe(status);
    expect(apiErr.detail).toBe(detail);
  });
}

describe("projectsApi", () => {
  it("lists projects as ProjectListResponse", async () => {
    const payload = {
      success: true,
      data: [{ id: "p1", name: "A" }],
      count: 1,
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload));
    const res = await projectsApi.list();
    expect(res.count).toBe(1);
    expect(res.data[0].name).toBe("A");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/projects",
      expect.objectContaining({
        headers: { "Content-Type": "application/json" },
      }),
    );
  });

  it("creates a project with name/description body", async () => {
    const payload = {
      success: true,
      data: { id: "p1", name: "Alpha", description: null },
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload, 201));
    const res = await projectsApi.create("Alpha", "desc");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects");
    expect(JSON.parse(init.body as string)).toEqual({
      name: "Alpha",
      description: "desc",
    });
    expect(res.data.description).toBeNull();
  });

  it("throws ApiError with backend detail when project missing", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Project 123 not found." }, 404),
    );
    await expectApiError(projectsApi.get("123"), 404, "Project 123 not found.");
  });
});

describe("sourcesApi", () => {
  const source: SourceResponse = {
    id: "s1",
    project_id: "p1",
    source_type: "text",
    original_filename: null,
    storage_key: null,
    mime_type: "text/plain",
    file_size: 42,
    language: "en",
    status: "ready",
    source_metadata: null,
    created_at: "2025-01-01T00:00:00Z",
  };

  it("lists sources under the project route", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: [source], count: 1 }));
    const res = await sourcesApi.list("p1");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/projects/p1/sources",
      expect.anything(),
    );
    expect(res.count).toBe(1);
  });

  it("ingests text via the text endpoint", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: source }, 201));
    await sourcesApi.ingestText("p1", "hello world", "en");
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/sources/text");
    expect(JSON.parse(init.body as string)).toEqual({
      text: "hello world",
      language: "en",
    });
  });

  it("routes TXT files to the /file endpoint with multipart body", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: source }, 201));
    const file = new File(["data"], "notes.txt", { type: "text/plain" });
    await sourcesApi.ingestFile("p1", file);
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/sources/file");
    expect(init.method).toBe("POST");
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("routes PDF/DOCX files to the /document endpoint", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: source }, 201));
    const pdf = new File(["%PDF"], "report.pdf", { type: "application/pdf" });
    await sourcesApi.ingestFile("p1", pdf);
    const [url] = mockFetch.mock.calls[0] as [string];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/sources/document");
  });

  it("surfaces validation errors as ApiError (400)", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: "Only PDF and DOCX files are supported." }, 400),
    );
    await expectApiError(
      sourcesApi.ingestFile("p1", new File(["x"], "a.exe", { type: "application/octet-stream" })),
      400,
      "Only PDF and DOCX files are supported.",
    );
  });
});

describe("configurationsApi", () => {
  it("creates a configuration with the payload", async () => {
    const payload = {
      success: true,
      data: {
        id: "c1",
        project_id: "p1",
        target_audience: "CEOs",
        tone: "professional",
        language: "English",
        detail_level: "standard",
        communication_objective: "inform",
        content_style: null,
        custom_instructions: null,
        created_at: "2025-01-01T00:00:00Z",
      },
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload, 201));
    const res = await configurationsApi.create("p1", {
      language: "English",
      tone: "professional",
    });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/projects/p1/configurations");
    expect(JSON.parse(init.body as string)).toEqual({
      language: "English",
      tone: "professional",
    });
    expect(res.data.detail_level).toBe("standard");
  });
});

describe("contentIntelligenceApi", () => {
  it("queues analysis via POST", async () => {
    const payload = {
      success: true,
      data: { id: "ci1", status: "pending" },
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload, 202));
    const res = await contentIntelligenceApi.analyze("s1");
    expect(res.data.status).toBe("pending");
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/sources/s1/content-intelligence",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("fetches canonical content", async () => {
    const payload = { success: true, data: { id: "ci1", status: "completed" } };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload));
    const res = await contentIntelligenceApi.get("s1");
    expect(res.data.status).toBe("completed");
  });
});

describe("transformationsApi", () => {
  const job = {
    id: "j1",
    project_id: "p1",
    source_id: "s1",
    configuration_id: "c1",
    requested_outputs: { output_types: ["summary"] },
    status: "queued",
    progress: 0,
    error_message: null,
    started_at: null,
    completed_at: null,
    created_at: "2025-01-01T00:00:00Z",
  };

  it("creates a job with the transformation payload", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: job }, 201));
    const res = await transformationsApi.create({
      project_id: "p1",
      source_id: "s1",
      configuration_id: "c1",
      output_types: ["summary", "presentation"],
    });
    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/api/v1/transformations");
    expect(JSON.parse(init.body as string)).toEqual({
      project_id: "p1",
      source_id: "s1",
      configuration_id: "c1",
      output_types: ["summary", "presentation"],
    });
    expect(res.data.status).toBe("queued");
  });

  it("fetches a job by id", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: job }));
    const res = await transformationsApi.get("j1");
    expect(res.data.id).toBe("j1");
  });

  it("lists outputs for a job", async () => {
    mockFetch.mockResolvedValueOnce(jsonResponse({ success: true, data: [], count: 0 }));
    const res = await transformationsApi.listOutputs("j1");
    expect(res.count).toBe(0);
  });

  it("throws ApiError with 422 validation detail", async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ detail: [{ msg: "output_types must not be empty", type: "value_error" }] }, 422),
    );
    await transformationsApi
      .create({ project_id: "p1", source_id: "s1", configuration_id: "c1", output_types: [] })
      .catch((err: unknown) => {
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(422);
        expect(apiErr.detail).toBe("output_types must not be empty");
      });
  });
});

describe("outputsApi", () => {
  it("lists verification results for an output", async () => {
    const payload = {
      success: true,
      data: [{ id: "v1", output_id: "o1", overall_status: "warning" }],
      count: 1,
    };
    mockFetch.mockResolvedValueOnce(jsonResponse(payload));
    const res = await outputsApi.verify("o1");
    expect(res.count).toBe(1);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/outputs/o1/verification",
      expect.anything(),
    );
  });
});