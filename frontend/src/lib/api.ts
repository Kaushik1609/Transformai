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
 * Phase 11F adds the auth surface (register / login / verify / me / logout)
 * and transparent bearer-token attachment via lib/auth.
 * Phase 15 moves login to email + password and adds forgot/reset-password.
 */

import { authHeaders, clearAuthToken, getAuthToken } from "./auth";

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
// Response types — auth (Phase 11F)
// ---------------------------------------------------------------------------

export type OtpChannel = "email" | "mobile";

export interface UserSummary {
  id: string;
  email: string;
  name: string;
  role: string;
}

export interface OtpDeliveryDetails {
  channel: string;
  identifier: string;
  resend_after_seconds: number;
  delivery_status?: string;
}

export interface RegisterResponse {
  success: boolean;
  data: OtpDeliveryDetails;
  message: string;
}

export interface LoginResponse {
  success: boolean;
  data: OtpDeliveryDetails;
  message: string;
}

export interface PasswordResetResponse {
  success: boolean;
  message: string;
}

export interface AuthTokenResponse {
  success: boolean;
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserSummary;
}

export interface MeResponse {
  success: boolean;
  data: UserSummary;
}

export interface LogoutResponse {
  success: boolean;
}

export interface AdminUserSummary {
  id: string;
  email: string;
  name: string;
  role: string;
  mobile_number: string | null;
  created_at: string;
}

export interface AdminUserListResponse {
  success: boolean;
  data: AdminUserSummary[];
  count: number;
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

export type InformationClassification =
  | "PUBLIC"
  | "INTERNAL"
  | "CONFIDENTIAL"
  | "RESTRICTED";

export function getSourceClassification(
  source: SourceResponse,
): InformationClassification {
  const metaClass = source.source_metadata?.classification;
  if (
    metaClass === "PUBLIC" ||
    metaClass === "INTERNAL" ||
    metaClass === "CONFIDENTIAL" ||
    metaClass === "RESTRICTED"
  ) {
    return metaClass as InformationClassification;
  }
  if (
    source.classification === "PUBLIC" ||
    source.classification === "INTERNAL" ||
    source.classification === "CONFIDENTIAL" ||
    source.classification === "RESTRICTED"
  ) {
    return source.classification as InformationClassification;
  }
  return "INTERNAL";
}

export function getPolicyPosture(
  classification: InformationClassification,
): string {
  switch (classification) {
    case "PUBLIC":
      return "Cloud Allowed";
    case "INTERNAL":
      return "Controlled Processing";
    case "CONFIDENTIAL":
      return "Private / Local Required";
    case "RESTRICTED":
      return "Private / Local Required (Cloud Denied)";
    default:
      return "Controlled Processing";
  }
}

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
  classification?: InformationClassification;
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
  source_id: string | null;
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
  configuration_id: string;
  /** One of source_id OR prompt is required (Phase 15). */
  source_id?: string;
  prompt?: string;
  output_types: OutputTypeId[];
  llm_provider?: string;
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

// ---------------------------------------------------------------------------
// Dissemination Control (Phase 2D)
// ---------------------------------------------------------------------------

export type DisseminationDestination =
  | "INTERNAL"
  | "REVIEW"
  | "DOWNLOAD"
  | "PRESENTATION"
  | "PUBLIC_WEB"
  | "LINKEDIN"
  | "X";

export type DisseminationDecisionOutcome = "ALLOW" | "BLOCK" | "REVIEW";

export interface DisseminationDecision {
  allowed: boolean;
  decision: DisseminationDecisionOutcome;
  classification: string;
  destination: string;
  reason: string;
  policy_id: string;
  artifact_hash?: string | null;
  signature?: string | null;
  provenance_id?: string | null;
  approval_id?: string | null;
  details?: Record<string, unknown>;
}

export interface DisseminationReportResponse {
  success: boolean;
  output_id: string;
  output_type: string;
  classification: string;
  destinations: Record<string, DisseminationDecision>;
}

export interface DisseminateResponse {
  success: boolean;
  data: DisseminationDecision;
}


// ---------------------------------------------------------------------------
// Human Approval & Controlled Release (Phase 2F)
// ---------------------------------------------------------------------------

export type ApprovalStatus =
  | "HARD_BLOCKED"
  | "NOT_REQUIRED"
  | "PENDING_APPROVAL"
  | "APPROVED"
  | "REJECTED"
  | "REVOKED";

export interface DestinationApprovalDetail {
  destination: string;
  approval_status: ApprovalStatus;
  approval_id?: string | null;
  decision?: string | null;
  approver_id?: string | null;
  approver_email?: string | null;
  approver_role?: string | null;
  approved_at?: string | null;
  rejection_reason?: string | null;
  comments?: string | null;
  self_approved: boolean;
  policy_reason?: string | null;
  classification_snapshot?: string | null;
  verification_status_snapshot?: string | null;
}

export interface ApprovalStatusResponse {
  success: boolean;
  output_id: string;
  classification: string;
  destinations: Record<string, DestinationApprovalDetail>;
  latest_approval_id?: string | null;
}

export interface ApprovalActionRequest {
  destination: string;
  action: "approve" | "reject";
  comments?: string;
  rejection_reason?: string;
}

export interface ApprovalActionResponse {
  success: boolean;
  data: DestinationApprovalDetail;
}


// ---------------------------------------------------------------------------
// Evidence & Provenance (Phase 2E)
// ---------------------------------------------------------------------------

export interface EvidenceCitationLineage {
  chunk_id?: string | null;
  source_id?: string | null;
  chunk_index: number;
  content_hash?: string | null;
  relevance_score?: number | null;
  excerpt: string;
}

export interface ProvenanceRecord {
  provenance_id: string;
  version: string;
  created_at: string;
  source: {
    source_id?: string | null;
    source_type?: string | null;
    original_filename?: string | null;
    source_content_hash?: string | null;
    classification: string;
    created_at?: string | null;
    source_version?: string | null;
  };
  evidence: {
    retrieval_method: string;
    chunks_count: number;
    citations: EvidenceCitationLineage[];
  };
  transformation: {
    transformation_id?: string | null;
    job_id: string;
    project_id: string;
    requested_outputs: string[];
    prompt_provided: boolean;
  };
  policy_routing: {
    classification: string;
    processing_route: string;
    provider_id: string;
    model_id: string;
    provider_category: string;
    policy_id: string;
    routing_reason: string;
  };
  generator: {
    output_type: string;
    generator_class: string;
    generator_version?: string | null;
    schema_name?: string | null;
    schema_version?: string | null;
    prompt_identifier?: string | null;
  };
  verification: {
    verification_result_id?: string | null;
    has_verification: boolean;
    overall_status?: string | null;
    grounding_score?: number | null;
    consistency_score?: number | null;
    claims_checked?: number | null;
    claims_supported?: number | null;
  };
  dissemination: {
    policy_id: string;
    primary_destination: string;
    primary_decision: string;
    primary_allowed: boolean;
  };
  integrity: {
    algorithm: string;
    content_digest?: string | null;
    representation?: string | null;
    ledger_status?: string | null;
    ledger_reference?: string | null;
  };
  audit: {
    provenance_event_type: string;
    recorded_at: string;
  };
  extensions?: {
    approval_id?: string | null;
    signature?: string | null;
    signature_algorithm?: string | null;
    airgap_bundle_id?: string | null;
  };
}

export interface ProvenanceResponse {
  success: boolean;
  output_id: string;
  data: ProvenanceRecord;
}


// ---------------------------------------------------------------------------
// Cryptographic Integrity & Artifact Hashing (Phase 2G)
// ---------------------------------------------------------------------------

export type IntegrityStatus = "VERIFIED" | "INVALID" | "UNAVAILABLE";

export interface OutputIntegrityDetail {
  status: IntegrityStatus;
  algorithm: string;
  artifact_hash?: string | null;
  companion_hashes?: Record<string, string>;
  provenance_id?: string | null;
  provenance_hash?: string | null;
  approval_id?: string | null;
  recorded_at?: string | null;
  details?: Record<string, unknown>;
}

export interface OutputIntegrityResponse {
  success: boolean;
  output_id: string;
  data: OutputIntegrityDetail;
}

export interface IntegrityVerifyResponse {
  success: boolean;
  output_id: string;
  data: OutputIntegrityDetail;
}

// ---------------------------------------------------------------------------
// Digital Signatures & Trusted Artifact Signing (Phase 2H)
// ---------------------------------------------------------------------------

export type SignatureStatus = "VALID" | "INVALID" | "UNAVAILABLE";

export interface OutputSignatureDetail {
  status: SignatureStatus;
  algorithm?: string | null;
  key_id?: string | null;
  signature?: string | null;
  signed_payload_hash?: string | null;
  signed_integrity_hash?: string | null;
  signed_provenance_hash?: string | null;
  provider?: string | null;
  signed_at?: string | null;
  details?: Record<string, unknown>;
}

export interface OutputSignatureResponse {
  success: boolean;
  output_id: string;
  data: OutputSignatureDetail;
}

export interface SignatureVerifyResponse {
  success: boolean;
  output_id: string;
  data: OutputSignatureDetail;
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

export interface FactVerificationEvidenceResponse {
  source_id: string;
  chunk_id: string;
  chunk_index: number;
  evidence: string;
  relevance_score: number | null;
  overlap: number;
  numeric_conflict: boolean;
  date_conflict: boolean;
}

export interface FactVerificationClaimResponse {
  id: string;
  text: string;
  claim_type: string;
  verdict: "SUPPORTED" | "CONTRADICTED" | "UNVERIFIED";
  reason: string;
  overlap: number;
  evidence: FactVerificationEvidenceResponse[];
}

export interface FactVerificationResultResponse {
  report_id: string;
  output_id: string;
  overall_status: "passed" | "warning" | "failed";
  summary: string;
  claims_checked: number;
  claims_supported: number;
  claims_contradicted: number;
  claims_unverified: number;
  claims: FactVerificationClaimResponse[];
}

export interface FactVerificationResponse {
  success: boolean;
  data: FactVerificationResultResponse;
}

// ---------------------------------------------------------------------------
// Response types — trust status + cross-output consistency (Phase 12B)
// ---------------------------------------------------------------------------

export interface TrustSignalResponse {
  category: string;
  present: boolean;
  status: "positive" | "warning" | "failure" | "missing";
  reason_code: string;
  detail: string;
}

export interface TrustStatusResponse {
  status: "TRUSTED" | "CAUTION" | "UNVERIFIED";
  reason_codes: string[];
  signals: TrustSignalResponse[];
  output_id: string;
  output_type: string;
}

export interface ConsistencyConflictResponse {
  category: "numeric" | "percentage" | "date";
  value_a: string;
  value_b: string;
  output_a_id: string;
  output_a_type: string;
  output_b_id: string;
  output_b_type: string;
  message: string;
}

export interface CrossOutputConsistencyResponse {
  status: "CONSISTENT" | "INCONSISTENT" | "NOT_APPLICABLE";
  completed_output_count: number;
  conflicts: ConsistencyConflictResponse[];
  checked_pairs: number;
  note: string;
}

export interface ConsistencyResultResponse {
  job_id: string;
  trust_statuses: TrustStatusResponse[];
  cross_output: CrossOutputConsistencyResponse;
}

export interface ConsistencyResponse {
  success: boolean;
  data: ConsistencyResultResponse;
}

// ---------------------------------------------------------------------------
// Response types — security operations (Phase 12D-G)
// ---------------------------------------------------------------------------

export interface SecurityEventResponse {
  event_type: string;
  outcome: string;
  timestamp: string;
  user_id: string | null;
  project_id: string | null;
  source_id: string | null;
  job_id: string | null;
  reason: string | null;
  /** Bounded, already-redacted operational details (never raw content). */
  details: Record<string, unknown>;
}

export interface SecurityEventListResponse {
  success: boolean;
  count: number;
  data: SecurityEventResponse[];
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

/**
 * Resolve the base URL for API requests.
 *
 * In the browser, when NEXT_PUBLIC_API_URL is unset, route requests through
 * Next.js's same-origin reverse proxy (/api/...) so that development servers
 * running on non-standard ports (such as 3001) are not blocked by backend CORS.
 */
export function getApiBaseUrl(): string {
  if (
    typeof window !== "undefined" &&
    process.env.NODE_ENV !== "test" &&
    !process.env.NEXT_PUBLIC_API_URL
  ) {
    return "";
  }
  return API_BASE_URL;
}

// ---------------------------------------------------------------------------
// Core fetch helpers
// ---------------------------------------------------------------------------

async function throwApiError(response: Response): Promise<never> {
  let detail = `HTTP ${response.status}`;
  try {
    const body: any = await response.json();
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      detail = body.detail.map((e: any) => e.msg).join("; ");
    } else if (body.detail && typeof body.detail === "object") {
      if (body.detail.message && body.detail.reason) {
        detail = `${body.detail.message} ${body.detail.reason}`;
      } else {
        detail = body.detail.message || body.detail.reason || JSON.stringify(body.detail);
      }
    }
  } catch {
    // ignore JSON parse failure — use status text
  }
  throw new ApiError(response.status, detail);
}

/**
 * React to an expired/invalid bearer token: drop stored credentials and
 * redirect the user to login with an explicit session-expired parameter.
 */
function handleUnauthorized(): void {
  clearAuthToken();
  if (typeof window !== "undefined") {
    try {
      if (
        !window.location.pathname.startsWith("/login") &&
        !window.location.pathname.startsWith("/register")
      ) {
        window.location.assign("/login?session_expired=true");
      }
    } catch {
      // Navigation not available in tests
    }
  }
}

const MAX_TRANSIENT_RETRIES = 2;
const RETRY_DELAY_MS = process.env.NODE_ENV === "test" ? 10 : 800;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isTransientStatus(status: number): boolean {
  return status === 502 || status === 503;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const hadBearerToken = getAuthToken() !== null;

  let lastError: unknown = null;
  for (let attempt = 0; attempt <= MAX_TRANSIENT_RETRIES; attempt++) {
    let response: Response | undefined;
    try {
      response = await fetch(url, {
        headers: {
          "Content-Type": "application/json",
          ...authHeaders(),
          ...options?.headers,
        },
        ...options,
      });
    } catch {
      lastError = new ApiError(0, `Network error: could not reach ${url}`);
      if (attempt < MAX_TRANSIENT_RETRIES) {
        await sleep(RETRY_DELAY_MS * (attempt + 1));
        continue;
      }
      throw lastError;
    }

    if (!response || typeof response.ok !== "boolean") {
      if (lastError) throw lastError;
      throw new ApiError(0, `Network error: could not reach ${url}`);
    }

    if (!response.ok) {
      if (isTransientStatus(response.status) && attempt < MAX_TRANSIENT_RETRIES) {
        let detail = `HTTP ${response.status}`;
        try {
          if (typeof response.clone === "function") {
            const body = await response.clone().json();
            if (body?.detail) detail = body.detail;
          } else if (typeof response.json === "function") {
            const body = await response.json();
            if (body?.detail) detail = body.detail;
          }
        } catch {
          // ignore
        }
        lastError = new ApiError(response.status, detail);
        await sleep(RETRY_DELAY_MS * (attempt + 1));
        continue;
      }
      if (response.status === 401 && hadBearerToken) {
        handleUnauthorized();
      }
      await throwApiError(response);
    }

    return response.json() as Promise<T>;
  }
  throw lastError || new ApiError(0, `Network error: could not reach ${url}`);
}

async function apiFetchForm<T>(
  path: string,
  formData: FormData,
  options?: RequestInit,
): Promise<T> {
  const url = `${getApiBaseUrl()}${path}`;
  const hadBearerToken = getAuthToken() !== null;

  let lastError: unknown = null;
  for (let attempt = 0; attempt <= MAX_TRANSIENT_RETRIES; attempt++) {
    let response: Response | undefined;
    try {
      response = await fetch(url, {
        ...options,
        method: options?.method ?? "POST",
        body: formData,
        headers: {
          ...authHeaders(),
          ...options?.headers,
        },
      });
    } catch {
      lastError = new ApiError(0, `Network error: could not reach ${url}`);
      if (attempt < MAX_TRANSIENT_RETRIES) {
        await sleep(RETRY_DELAY_MS * (attempt + 1));
        continue;
      }
      throw lastError;
    }

    if (!response || typeof response.ok !== "boolean") {
      if (lastError) throw lastError;
      throw new ApiError(0, `Network error: could not reach ${url}`);
    }

    if (!response.ok) {
      if (isTransientStatus(response.status) && attempt < MAX_TRANSIENT_RETRIES) {
        let detail = `HTTP ${response.status}`;
        try {
          if (typeof response.clone === "function") {
            const body = await response.clone().json();
            if (body?.detail) detail = body.detail;
          } else if (typeof response.json === "function") {
            const body = await response.json();
            if (body?.detail) detail = body.detail;
          }
        } catch {
          // ignore
        }
        lastError = new ApiError(response.status, detail);
        await sleep(RETRY_DELAY_MS * (attempt + 1));
        continue;
      }
      if (response.status === 401 && hadBearerToken) {
        handleUnauthorized();
      }
      await throwApiError(response);
    }

    return response.json() as Promise<T>;
  }
  throw lastError || new ApiError(0, `Network error: could not reach ${url}`);
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
  const url = `${getApiBaseUrl()}${path}${search}`;
  const fetchInit: RequestInit =
    init?.method === "POST"
      ? { method: "POST" as const, headers: authHeaders() }
      : { method: "GET" as const, headers: authHeaders() };
  const hadBearerToken = getAuthToken() !== null;

  let response: Response;
  try {
    response = await fetch(url, fetchInit);
  } catch {
    throw new ApiError(0, `Network error: could not reach ${url}`);
  }

  if (!response.ok) {
    if (response.status === 401 && hadBearerToken) {
      handleUnauthorized();
    }
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
// Auth API (Phase 11F, Phase 15 password login)
// ---------------------------------------------------------------------------

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
  mobile_number?: string;
  channel?: OtpChannel;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface VerifyOtpPayload {
  email: string;
  channel?: OtpChannel;
  mobile_number?: string;
  otp: string;
}

export interface ForgotPasswordPayload {
  email: string;
  channel?: OtpChannel;
  mobile_number?: string;
}

export interface ResetPasswordPayload {
  email: string;
  otp: string;
  new_password: string;
  channel?: OtpChannel;
  mobile_number?: string;
}

export const authApi = {
  /** Register a new analyst account (inactive until the OTP is verified). */
  register: (body: RegisterPayload) =>
    apiFetch<RegisterResponse>("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Log in with email + password and receive a short-lived JWT. */
  login: (body: LoginPayload) =>
    apiFetch<AuthTokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Exchange a registration OTP for a short-lived access token. */
  verifyOtp: (body: VerifyOtpPayload) =>
    apiFetch<AuthTokenResponse>("/api/v1/auth/verify", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Re-issue a registration OTP for a pending (inactive) account. */
  resendOtp: (body: ForgotPasswordPayload) =>
    apiFetch<LoginResponse>("/api/v1/auth/resend-otp", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Request a password-reset code (generic, non-enumerating response). */
  forgotPassword: (body: ForgotPasswordPayload) =>
    apiFetch<LoginResponse>("/api/v1/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Confirm a password-reset code and set the new password. */
  resetPassword: (body: ResetPasswordPayload) =>
    apiFetch<PasswordResetResponse>("/api/v1/auth/reset-password", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** Return the authenticated user's identity. */
  me: () => apiFetch<MeResponse>("/api/v1/auth/me"),

  /** Acknowledge logout (client clears its own token). */
  logout: () => apiFetch<LogoutResponse>("/api/v1/auth/logout", {
    method: "POST",
  }),
};

// ---------------------------------------------------------------------------
// Admin API (Phase 11F — admin-only)
// ---------------------------------------------------------------------------

export const adminApi = {
  /** List all users (requires an admin role token). */
  listUsers: () => apiFetch<AdminUserListResponse>("/api/v1/admin/users"),
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
  ingestText: (
    projectId: string,
    text: string,
    language = "en",
    classification?: InformationClassification,
  ) =>
    apiFetch<SourceDetailResponse>(
      `/api/v1/projects/${projectId}/sources/text`,
      {
        method: "POST",
        body: JSON.stringify({
          text,
          language,
          ...(classification ? { classification } : {}),
        }),
      },
    ),

  /**
   * Upload a source file. TXT goes through the /file endpoint, PDF/DOCX
   * through /document (matching the backend contract).
   */
  ingestFile: (
    projectId: string,
    file: File,
    classification?: InformationClassification,
  ) => {
    const name = file.name || "";
    const ext = name.includes(".")
      ? name.split(".").pop()!.toLowerCase()
      : "";
    const formData = new FormData();
    formData.append("file", file);
    formData.append("language", "en");
    if (classification) {
      formData.append("classification", classification);
    }
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

  /** Trust status + cross-output consistency for a transformation job. */
  consistency: (jobId: string) =>
    apiFetch<ConsistencyResponse>(`/api/v1/transformations/${jobId}/consistency`),

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

  /** Run Phase 11N fact verification for a completed output's claims. */
  verifyFacts: (outputId: string) =>
    apiFetch<FactVerificationResponse>(
      `/api/v1/outputs/${outputId}/verify-facts`,
      { method: "POST" },
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

  /**
   * Get dissemination policy evaluation for an output across destinations (Phase 2D).
   */
  dissemination: (outputId: string, destination?: string) =>
    apiFetch<DisseminationReportResponse>(
      `/api/v1/outputs/${outputId}/dissemination${destination ? `?destination=${encodeURIComponent(destination)}` : ""}`,
    ),

  /**
   * Request dissemination of an output to a target destination (Phase 2D).
   * Authoritatively evaluated by backend policy.
   */
  disseminate: (outputId: string, destination: string) =>
    apiFetch<DisseminateResponse>(
      `/api/v1/outputs/${outputId}/disseminate`,
      { method: "POST", body: JSON.stringify({ destination }) },
    ),

  /**
   * Get canonical provenance record for an output (Phase 2E).
   */
  provenance: (outputId: string) =>
    apiFetch<ProvenanceResponse>(
      `/api/v1/outputs/${outputId}/provenance`,
    ),

  /**
   * Get human approval status for an output across destinations (Phase 2F).
   */
  approval: (outputId: string, destination?: string) =>
    apiFetch<ApprovalStatusResponse>(
      `/api/v1/outputs/${outputId}/approval${destination ? `?destination=${encodeURIComponent(destination)}` : ""}`,
    ),

  /**
   * Submit an approval or rejection decision for a destination (Phase 2F).
   */
  submitApproval: (outputId: string, body: ApprovalActionRequest) =>
    apiFetch<ApprovalActionResponse>(
      `/api/v1/outputs/${outputId}/approval`,
      {
        method: "POST",
        body: JSON.stringify(body),
      },
    ),

  /**
   * Get cryptographic integrity record for an output (Phase 2G).
   */
  integrity: (outputId: string) =>
    apiFetch<OutputIntegrityResponse>(
      `/api/v1/outputs/${outputId}/integrity`,
    ),

  /**
   * Verify cryptographic integrity of output artifacts and provenance (Phase 2G).
   */
  verifyIntegrity: (outputId: string) =>
    apiFetch<IntegrityVerifyResponse>(
      `/api/v1/outputs/${outputId}/integrity/verify`,
      { method: "POST" },
    ),

  /**
   * Get digital signature record for an output (Phase 2H).
   */
  signature: (outputId: string) =>
    apiFetch<OutputSignatureResponse>(
      `/api/v1/outputs/${outputId}/signature`,
    ),

  /**
   * Verify digital signature and underlying integrity (Phase 2H).
   */
  verifySignature: (outputId: string) =>
    apiFetch<SignatureVerifyResponse>(
      `/api/v1/outputs/${outputId}/signature/verify`,
      { method: "POST" },
    ),
};

// ---------------------------------------------------------------------------
// Security operations API (Phase 12D-G — read-only)
// ---------------------------------------------------------------------------

export interface SecurityEventsQuery {
  projectId?: string;
  eventType?: string;
  limit?: number;
}

export const operationsApi = {
  /**
   * List bounded, owner-scoped security events (read-only observability).
   * Never returns source content, credentials, secrets, or other users' events.
   */
  securityEvents: (query: SecurityEventsQuery = {}) => {
    const params = new URLSearchParams();
    if (query.projectId) params.set("project_id", query.projectId);
    if (query.eventType) params.set("event_type", query.eventType);
    if (query.limit) params.set("limit", String(query.limit));
    const search = params.toString();
    return apiFetch<SecurityEventListResponse>(
      `/api/v1/operations/security-events${search ? `?${search}` : ""}`,
    );
  },
};