/**
 * TransformIQ — API Client
 *
 * Centralizes all backend communication.
 * The backend base URL is read from the NEXT_PUBLIC_API_URL environment variable.
 * Never put secrets or API keys here — all AI/LLM keys live on the backend only.
 *
 * Covers the Phase 2+ domain surface:
 *   projects, sources, configurations, content-intelligence,
 *   transformations, outputs, verification results, and artifact downloads.
 */

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ---------------------------------------------------------------------------
// Response types — health
// ---------------------------------------------------------------------------

export interface ApiErrorResponse {
  detail: string | { msg: string; type: string }[];
}

export interface HealthResponse {
  status: "ok";
  service: string;
  version: string;
  environment: string;
  uptime_seconds: number;
}

export interface ReadyCheck {
  database: string;
  redis: string;
  [key: string]: string;
}

export interface ReadyResponse {
  status: "ready" | "not_ready";
  checks: ReadyCheck;
}

// ---------------------------------------------------------------------------
// Response types — projects
// ---------------------------------------------------------------------------

export interface ProjectResponse {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectListResponse {
  success: boolean;
  data: ProjectResponse[];
  count: number;
}

export interface ProjectDetailResponse {
  success: boolean;
  data: ProjectResponse;
}

export interface DeleteResponse {
  success: boolean;
  message: string;
}

// ---------------------------------------------------------------------------
// Response types — sources
// ---------------------------------------------------------------------------

export interface SourceResponse {
  id: string;
  project_id: string;
  source_type: string;
  original_filename: string | null;
  storage_key: string | null;
  mime_type: string | null;
  file_size: number | null;
  language: string;
  status: string;
  source_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface SourceListResponse {
  success: boolean;
  data: SourceResponse[];
  count: number;
}

export interface SourceDetailResponse {
  success: boolean;
  data: SourceResponse;
}

// ---------------------------------------------------------------------------
// Response types — configurations
// ---------------------------------------------------------------------------

export interface ConfigurationResponse {
  id: string;
  project_id: string;
  target_audience: string | null;
  tone: string | null;
  language: string;
  detail_level: string | null;
  communication_objective: string | null;
  content_style: string | null;
  custom_instructions: string | null;
  created_at: string;
}

export interface ConfigurationListResponse {
  success: boolean;
  data: ConfigurationResponse[];
  count: number;
}

export interface ConfigurationDetailResponse {
  success: boolean;
  data: ConfigurationResponse;
}

export interface ConfigurationPayload {
  target_audience?: string | null;
  tone?: string | null;
  language: string;
  detail_level?: string | null;
  communication_objective?: string | null;
  content_style?: string | null;
  custom_instructions?: string | null;
}

// ---------------------------------------------------------------------------
// Response types — content intelligence
// ---------------------------------------------------------------------------

export interface CanonicalContentResponse {
  id: string;
  source_id: string;
  project_id: string;
  status: string;
  title: string | null;
  summary: string | null;
  metadata: Record<string, unknown>;
  topics: Record<string, unknown>[];
  entities: Record<string, unknown>[];
  key_points: Record<string, unknown>[];
  claims: Record<string, unknown>[];
  statistics: Record<string, unknown>[];
  dates: Record<string, unknown>[];
  recommendations: Record<string, unknown>[];
  source_references: Record<string, unknown>[];
  error_message: string | null;
  created_at: string;
  updated_at: string;
  analyzed_at: string | null;
}

export interface ContentIntelligenceResponse {
  success: boolean;
  data: CanonicalContentResponse;
}

// ---------------------------------------------------------------------------
// Response types — transformations / outputs / verification
// ---------------------------------------------------------------------------

export type OutputTypeId =
  | "summary"
  | "linkedin"
  | "x"
  | "advisory"
  | "infographic"
  | "presentation"
  | "video";

export interface TransformationJobResponse {
  id: string;
  project_id: string;
  source_id: string;
  configuration_id: string;
  requested_outputs: Record<string, unknown> | null;
  status: string;
  progress: number;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface TransformationJobPayload {
  project_id: string;
  source_id: string;
  configuration_id: string;
  output_types: OutputTypeId[];
}

export interface TransformationJobDetailResponse {
  success: boolean;
  data: TransformationJobResponse;
}

export interface TransformationJobListResponse {
  success: boolean;
  data: TransformationJobResponse[];
  count: number;
}

export interface OutputResponse {
  id: string;
  job_id: string;
  output_type: string;
  status: string;
  structured_content: Record<string, unknown> | null;
  text_content: string | null;
  storage_key: string | null;
  mime_type: string | null;
  output_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface OutputListResponse {
  success: boolean;
  data: OutputResponse[];
  count: number;
}

export interface OutputDetailResponse {
  success: boolean;
  data: OutputResponse;
}

export interface VerificationResultResponse {
  id: string;
  output_id: string;
  overall_status: string;
  grounding_score: number | null;
  consistency_score: number | null;
  claims_checked: number | null;
  claims_supported: number | null;
  warnings: Record<string, unknown> | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export interface VerificationListResponse {
  success: boolean;
  data: VerificationResultResponse[];
  count: number;
}

export type ArtifactRole = "primary" | "pdf" | "srt";

export interface DownloadResult {
  blob: Blob;
  filename?: string;
}

// ---------------------------------------------------------------------------
// Error class
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

/**
 * Map an API failure to a user-friendly message.
 *
 * Network failures (status 0) and server errors (5xx) are replaced with the
 * supplied fallback so the UI never displays raw transport/HTTP noise.
 */
export function errorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 0 || err.status >= 500) return fallback;
    return err.detail.length > 0 ? err.detail : fallback;
  }
  return fallback;
}

// ---------------------------------------------------------------------------
// Core fetch helpers
// ---------------------------------------------------------------------------

async function throwApiError(response: Response): Promise<never> {
  let detail = `HTTP ${response.status}`;
  try {
    const body: ApiErrorResponse = await response.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      detail = body.detail.map((e) => e.msg).join("; ");
    }
  } catch {
    // ignore JSON parse failure — use status text
  }
  throw new ApiError(response.status, detail);
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        ...options?.headers,
      },
      ...options,
    });
  } catch {
    throw new ApiError(0, `Network error: could not reach ${url}`);
  }

  if (!response.ok) {
    await throwApiError(response);
  }

  return response.json() as Promise<T>;
}

async function apiFetchForm<T>(path: string, formData: FormData): Promise<T> {
  const url = `${API_BASE_URL}${path}`;

  let response: Response;
  try {
    // The browser sets the multipart content-type with its boundary for us.
    response = await fetch(url, { method: "POST", body: formData });
  } catch {
    throw new ApiError(0, `Network error: could not reach ${url}`);
  }

  if (!response.ok) {
    await throwApiError(response);
  }

  return response.json() as Promise<T>;
}

function parseFilenameFromDisposition(
  disposition: string | null,
): string | undefined {
  if (!disposition) return undefined;
  const match = /filename="?(.+?)"?\s*(?:;|$)/.exec(disposition);
  return match ? match[1] : undefined;
}

async function apiFetchBlob(
  path: string,
  query?: Record<string, string>,
  init?: { method?: "GET" | "POST" },
): Promise<DownloadResult> {
  const search = query
    ? `?${new URLSearchParams(query).toString()}`
    : "";
  const url = `${API_BASE_URL}${path}${search}`;
  const fetchInit =
    init?.method === "POST" ? { method: "POST" as const } : undefined;

  let response: Response;
  try {
    response = await fetch(url, fetchInit);
  } catch {
    throw new ApiError(0, `Network error: could not reach ${url}`);
  }

  if (!response.ok) {
    await throwApiError(response);
  }

  const filename = parseFilenameFromDisposition(
    response.headers.get("content-disposition"),
  );
  const blob = await response.blob();
  return { blob, filename };
}

// ---------------------------------------------------------------------------
// Health API
// ---------------------------------------------------------------------------

export const healthApi = {
  /** Liveness check — returns 200 when the backend process is alive. */
  health: () => apiFetch<HealthResponse>("/health"),

  /** Readiness check — returns 200 when all dependencies are connected. */
  ready: () => apiFetch<ReadyResponse>("/ready"),
};

// ---------------------------------------------------------------------------
// Projects API
// ---------------------------------------------------------------------------

export const projectsApi = {
  /** List all projects for the current user. */
  list: () => apiFetch<ProjectListResponse>("/api/v1/projects"),

  /** Create a project. */
  create: (name: string, description?: string | null) =>
    apiFetch<ProjectDetailResponse>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, description: description ?? null }),
    }),

  /** Get a single project with ownership verification. */
  get: (projectId: string) =>
    apiFetch<ProjectDetailResponse>(`/api/v1/projects/${projectId}`),

  /** Delete a project. */
  remove: (projectId: string) =>
    apiFetch<DeleteResponse>(`/api/v1/projects/${projectId}`, {
      method: "DELETE",
    }),
};

// ---------------------------------------------------------------------------
// Sources API
// ---------------------------------------------------------------------------

export const sourcesApi = {
  /** List sources for a project (newest first per backend ordering). */
  list: (projectId: string) =>
    apiFetch<SourceListResponse>(`/api/v1/projects/${projectId}/sources`),

  /** Ingest a direct text source. */
  ingestText: (projectId: string, text: string, language = "en") =>
    apiFetch<SourceDetailResponse>(
      `/api/v1/projects/${projectId}/sources/text`,
      {
        method: "POST",
        body: JSON.stringify({ text, language }),
      },
    ),

  /**
   * Upload a source file. TXT goes through the /file endpoint, PDF/DOCX
   * through /document (matching the backend contract).
   */
  ingestFile: (projectId: string, file: File) => {
    const name = file.name || "";
    const ext = name.includes(".")
      ? name.split(".").pop()!.toLowerCase()
      : "";
    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", "en");
    const endpoint =
      ext === "pdf" || ext === "docx"
        ? `${projectId}/sources/document`
        : `${projectId}/sources/file`;
    return apiFetchForm<SourceDetailResponse>(
      `/api/v1/projects/${endpoint}`,
      formData,
    );
  },

  /** Get a single source. */
  get: (sourceId: string) =>
    apiFetch<SourceDetailResponse>(`/api/v1/sources/${sourceId}`),

  /** Delete a source. */
  remove: (sourceId: string) =>
    apiFetch<DeleteResponse>(`/api/v1/sources/${sourceId}`, {
      method: "DELETE",
    }),
};

// ---------------------------------------------------------------------------
// Configurations API
// ---------------------------------------------------------------------------

export const configurationsApi = {
  /** List configurations for a project. */
  list: (projectId: string) =>
    apiFetch<ConfigurationListResponse>(
      `/api/v1/projects/${projectId}/configurations`,
    ),

  /** Create a generation configuration for a project. */
  create: (projectId: string, body: ConfigurationPayload) =>
    apiFetch<ConfigurationDetailResponse>(
      `/api/v1/projects/${projectId}/configurations`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),
};

// ---------------------------------------------------------------------------
// Content Intelligence API
// ---------------------------------------------------------------------------

export const contentIntelligenceApi = {
  /** Queue content intelligence analysis for a ready source. */
  analyze: (sourceId: string) =>
    apiFetch<ContentIntelligenceResponse>(
      `/api/v1/sources/${sourceId}/content-intelligence`,
      { method: "POST" },
    ),

  /** Get canonical content for a source. */
  get: (sourceId: string) =>
    apiFetch<ContentIntelligenceResponse>(
      `/api/v1/sources/${sourceId}/content-intelligence`,
    ),
};

// ---------------------------------------------------------------------------
// Transformations API
// ---------------------------------------------------------------------------

export const transformationsApi = {
  /** Create a transformation job (also enqueues it for async processing). */
  create: (body: TransformationJobPayload) =>
    apiFetch<TransformationJobDetailResponse>("/api/v1/transformations", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Get a transformation job with ownership verification. */
  get: (jobId: string) =>
    apiFetch<TransformationJobDetailResponse>(
      `/api/v1/transformations/${jobId}`,
    ),

  /** List all outputs for a transformation job. */
  listOutputs: (jobId: string) =>
    apiFetch<OutputListResponse>(`/api/v1/transformations/${jobId}/outputs`),

  /** List the transformation job history for a project (newest first). */
  listByProject: (projectId: string) =>
    apiFetch<TransformationJobListResponse>(
      `/api/v1/projects/${projectId}/transformations`,
    ),

  /** Cancel a queued/running job. */
  cancel: (jobId: string) =>
    apiFetch<TransformationJobDetailResponse>(
      `/api/v1/transformations/${jobId}/cancel`,
      { method: "POST" },
    ),
};

// ---------------------------------------------------------------------------
// Outputs API
// ---------------------------------------------------------------------------

export const outputsApi = {
  /** Get a single output. */
  get: (outputId: string) =>
    apiFetch<OutputDetailResponse>(`/api/v1/outputs/${outputId}`),

  /** List verification results for an output. */
  verify: (outputId: string) =>
    apiFetch<VerificationListResponse>(
      `/api/v1/outputs/${outputId}/verification`,
    ),

  /**
   * Download an output artifact via the Phase 8E endpoint.
   * The storage key is resolved server-side; the browser only ever sees
   * the returned file bytes (never a storage URL).
   */
  download: (outputId: string, artifact: ArtifactRole = "primary") =>
    apiFetchBlob(`/api/v1/outputs/${outputId}/download`, { artifact }),

  /**
   * Export a completed Executive Summary / Advisory output to DOCX or PDF.
   * The document is rendered server-side from the stored structured content.
   */
  export: (outputId: string, format: "docx" | "pdf") =>
    apiFetchBlob(
      `/api/v1/outputs/${outputId}/export`,
      { format },
      { method: "POST" },
    ),
};