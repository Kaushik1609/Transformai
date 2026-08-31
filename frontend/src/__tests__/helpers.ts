/**
 * Shared test helpers — mocked fetch / fake backend.
 */
import {
  type OutputResponse,
  type ProjectResponse,
  type SourceResponse,
  type ConfigurationResponse,
  type TransformationJobResponse,
  type VerificationResultResponse,
} from "@/lib/api";

export type FetchMock = jest.Mock<
  Promise<Response>,
  [RequestInfo | URL, RequestInit?]
>;

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    headers: new Headers(),
    blob: async () => new Blob(),
  } as unknown as Response;
}

export function blobResponse(
  blob: Blob,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({}),
    headers: new Headers(headers),
    blob: async () => blob,
  } as unknown as Response;
}

// ---------------------------------------------------------------------------
// E2E fake backend (mirrors the routes the workspace consumes)
// ---------------------------------------------------------------------------

export class FakeBackend {
  projects: ProjectResponse[];
  sources: SourceResponse[];
  configs: ConfigurationResponse[];
  job: TransformationJobResponse | null;
  outputs: OutputResponse[];
  verifications: VerificationResultResponse[] | null;
  jobPolls: number;
  jobFinalStatus: string;
  contentIntelligenceStatus: number;
  /** When set, POST /transformations returns this job instead of a queued one. */
  jobOnCreate: TransformationJobResponse | null;
  /** Transformations history served for GET /api/v1/projects/{id}/transformations. */
  history: TransformationJobResponse[];

  constructor(projectId = "11111111-1111-1111-1111-111111111111") {
    this.projects = [
      {
        id: projectId,
        user_id: "00000000-0000-0000-0000-000000000001",
        name: "Demo Project",
        description: "E2E test project",
        created_at: "2025-01-01T00:00:00Z",
        updated_at: "2025-01-01T00:00:00Z",
      },
    ];
    this.sources = [];
    this.configs = [];
    this.job = null;
    this.outputs = [];
    this.verifications = null;
    this.jobPolls = 0;
    this.jobFinalStatus = "completed";
    this.contentIntelligenceStatus = 404;
    this.jobOnCreate = null;
    this.history = [];
  }

  seedSource(source: SourceResponse) {
    this.sources = [source, ...this.sources];
  }

  seedConfig(config: ConfigurationResponse) {
    this.configs = [config, ...this.configs];
  }

  seedCompletedJob(job: TransformationJobResponse, outputs: OutputResponse[]) {
    this.job = { ...job, status: "completed", progress: 100 };
    this.outputs = outputs;
    this.jobPolls = 0;
    this.jobFinalStatus = "completed";
  }

  seedTerminalJob(job: TransformationJobResponse, outputs: OutputResponse[]) {
    this.job = job;
    this.outputs = outputs;
    this.jobPolls = 0;
    this.jobFinalStatus = job.status;
  }

  seedOutputs(outputs: OutputResponse[]) {
    this.outputs = outputs;
  }

  nextJobPoll(): TransformationJobResponse {
    if (!this.job) throw new Error("no job seeded");
    this.jobPolls += 1;
    if (this.jobPolls >= 3) {
      this.job = { ...this.job, status: this.jobFinalStatus, progress: 100 };
    } else if (this.jobPolls === 2) {
      this.job = { ...this.job, status: "running", progress: 0 };
    }
    return this.job;
  }

  handler() {
    return async (input: RequestInfo | Request): Promise<Response> => {
      const url = String(input);
      const withoutQuery = url.split("?")[0];
      const path = withoutQuery.replace("http://localhost:8000", "");

      // Projects
      if (path === "/api/v1/projects" ) {
        return jsonResponse({ success: true, data: this.projects, count: this.projects.length });
      }
      if (/^\/api\/v1\/projects\/[^/]+$/.test(path)) {
        const project = this.projects[0];
        return jsonResponse({ success: true, data: project });
      }

      // Sources
      if (path.endsWith("/sources")) {
        return jsonResponse({ success: true, data: this.sources, count: this.sources.length });
      }
      if (path.endsWith("/sources/text")) {
        return jsonResponse(
          { success: true, data: this.sources[0] ?? null },
          201,
        );
      }

      // Configurations
      if (path.endsWith("/configurations")) {
        return jsonResponse({ success: true, data: this.configs, count: this.configs.length });
      }

      // Content intelligence
      if (path.endsWith("/content-intelligence")) {
        if (this.contentIntelligenceStatus === 404) {
          return jsonResponse(
            { detail: "Content intelligence has not been created." },
            404,
          );
        }
        return jsonResponse(
          { success: true, data: { id: "1", status: "completed" } },
          200,
        );
      }

      // Transformations
      const history = /^\/api\/v1\/projects\/([^/]+)\/transformations$/.exec(path);
      if (history) {
        return jsonResponse({
          success: true,
          data: this.history,
          count: this.history.length,
        });
      }
      if (path === "/api/v1/transformations") {
        this.job =
          this.jobOnCreate ?? {
            id: "22222222-2222-2222-2222-222222222222",
            project_id: "11111111-1111-1111-1111-111111111111",
            source_id: this.sources[0]?.id ?? "source",
            configuration_id: this.configs[0]?.id ?? "config",
            requested_outputs: { output_types: ["summary"] },
            status: "queued",
            progress: 0,
            error_message: null,
            started_at: null,
            completed_at: null,
            created_at: "2025-01-01T00:00:00Z",
          };
        return jsonResponse(
          { success: true, data: this.job },
          201,
        );
      }
      const jobGet = /^\/api\/v1\/transformations\/([^/]+)$/.exec(path);
      if (jobGet) {
        return jsonResponse({ success: true, data: this.nextJobPoll() });
      }
      if (path.endsWith("/outputs")) {
        return jsonResponse({ success: true, data: this.outputs, count: this.outputs.length });
      }

      // Outputs
      const verification = /^\/api\/v1\/outputs\/([^/]+)\/verification$/.exec(path);
      if (verification) {
        if (this.verifications === null) {
          return jsonResponse({ success: true, data: [], count: 0 });
        }
        return jsonResponse({
          success: true,
          data: this.verifications,
          count: this.verifications.length,
        });
      }
      const download = /^\/api\/v1\/outputs\/([^/]+)\/download/.exec(path);
      if (download) {
        return blobResponse(
          new Blob(["mock-bytes"], { type: "text/plain" }),
          200,
          { "content-disposition": 'attachment; filename="summary.txt"' },
        );
      }

      const exportOut = /^\/api\/v1\/outputs\/([^/]+)\/export/.exec(path);
      if (exportOut) {
        return blobResponse(
          new Blob(["%PDF-mock"], { type: "application/pdf" }),
          200,
          { "content-disposition": 'attachment; filename="summary.pdf"' },
        );
      }

      return jsonResponse({ detail: `No mock route for ${path}` }, 404);
    };
  }
}