import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { components } from "./schema";

export type SourceInput = components["schemas"]["SourceInput"];
export type PreparedSourceResponse = components["schemas"]["PrepareSourceResponse"];
export type TaskSummaryResponse = components["schemas"]["TaskSummary"];

export class ApiError extends Error {
  constructor(public readonly status: number) {
    super(`API request failed with status ${status}.`);
  }
}

export async function serverIsAlive(): Promise<boolean> {
  const api = createClient<paths>({
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  });
  const { data, error } = await api.GET("/health/live");

  if (error || data?.status !== "alive") {
    return false;
  }

  return true;
}

export async function loadTaskWorkspace(accessToken: string) {
  const api = authenticatedApi(accessToken);
  const identityResult = await api.GET("/auth/me");
  if (!identityResult.data) {
    throw new ApiError(identityResult.response.status);
  }
  const taskResult = await api.GET("/tasks");
  if (!taskResult.data) {
    throw new ApiError(taskResult.response.status);
  }
  return {
    identity: identityResult.data,
    tasks: taskResult.data.items,
  };
}

function authenticatedApi(accessToken: string) {
  return createClient<paths>({
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

export async function prepareTaskSource(
  accessToken: string,
  source: SourceInput,
): Promise<PreparedSourceResponse> {
  const result = await authenticatedApi(accessToken).POST("/task-creation/prepare", {
    body: source,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function confirmTaskCreation(
  accessToken: string,
  idempotencyKey: string,
  source: SourceInput,
): Promise<TaskSummaryResponse> {
  const result = await authenticatedApi(accessToken).POST("/task-creation/confirm", {
    body: { idempotency_key: idempotencyKey, source },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.task;
}

export async function renameTask(
  accessToken: string,
  taskId: string,
  displayName: string,
): Promise<TaskSummaryResponse> {
  const result = await authenticatedApi(accessToken).PATCH("/tasks/{task_id}", {
    params: { path: { task_id: taskId } },
    body: { display_name: displayName },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
