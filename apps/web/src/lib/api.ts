/** Thin client for the FastAPI backend. All browser traffic goes through the API. */

import type { components } from "@/lib/api-types";

/** Response and request shapes, generated from the API's OpenAPI document (ADR-0011). */
export type Schemas = components["schemas"];

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
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let body: ApiErrorBody | null = null;
    try {
      body = ((await response.json()) as { error: ApiErrorBody }).error;
    } catch {
      body = null;
    }
    throw new ApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export type Liveness = Schemas["Liveness"];
export type Readiness = Schemas["Readiness"];
