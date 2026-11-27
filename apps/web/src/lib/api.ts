/** Thin client for the FastAPI backend. All browser traffic goes through the API. */

import type { components } from "@/lib/api-types";

/** Response and request shapes, generated from the API's OpenAPI document (ADR-0011). */
export type Schemas = components["schemas"];

export type Liveness = Schemas["Liveness"];
export type Readiness = Schemas["Readiness"];
export type Me = Schemas["Me"];
export type Membership = Schemas["MembershipOut"];
export type Organisation = Schemas["OrganisationOut"];
export type Member = Schemas["MemberOut"];
export type Role = Schemas["Role"];
export type Project = Schemas["ProjectOut"];
export type ProjectCreate = Schemas["ProjectCreate"];
export type ProjectUpdate = Schemas["ProjectUpdate"];
export type ProjectPage = Schemas["Page_ProjectOut_"];
export type AuditEvent = Schemas["AuditEventOut"];
export type AuditPage = Schemas["Page_AuditEventOut_"];
export type DocumentSummary = Schemas["DocumentOut"];
export type DocumentDetail = Schemas["DocumentDetail"];
export type DocumentVersion = Schemas["VersionOut"];
export type ProcessingRun = Schemas["RunOut"];
export type UploadStarted = Schemas["UploadStarted"];
export type Extraction = Schemas["Extraction"];
export type ExtractedBlock = Schemas["Block"];
export type BlockLocation = Schemas["Location"];

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Spec §6.2 error envelope. Mirrors workforce_contracts.ErrorBody; the error handlers build it
 * outside FastAPI's response models, so it is not in the generated types.
 */
export interface ApiErrorBody {
  code: string;
  message: string;
  correlation_id: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: ApiErrorBody | null,
  ) {
    super(body?.message ?? `Request failed with status ${status}`);
  }

  get code(): string | undefined {
    return this.body?.code;
  }

  get correlationId(): string | undefined {
    return this.body?.correlation_id;
  }
}

/** Parse a failed response into an ApiError, tolerating bodies that aren't the envelope. */
export async function toApiError(response: Response): Promise<ApiError> {
  try {
    const json: unknown = await response.json();
    const error = (json as { error?: unknown } | null)?.error;
    if (error && typeof error === "object" && "code" in error && "message" in error) {
      return new ApiError(response.status, error as ApiErrorBody);
    }
  } catch {
    // Not JSON: fall through.
  }
  return new ApiError(response.status, null);
}

export interface RequestOptions {
  token?: string | null;
  organisationId?: string | null;
  body?: unknown;
  idempotencyKey?: string;
  query?: Record<string, string | number | undefined | null>;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = new URL(`${API_BASE_URL}${path}`);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.organisationId) headers["X-Organisation-ID"] = options.organisationId;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, null);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function apiGet<T>(path: string, options?: RequestOptions): Promise<T> {
  return apiRequest<T>("GET", path, options);
}

/** A sentence for the person, never a stack trace. */
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 0) return "The API is not reachable. Is it running?";
    return err.body?.message ?? `Request failed (${err.status}).`;
  }
  return "Something went wrong.";
}
