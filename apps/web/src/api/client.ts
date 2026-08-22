import createClient from "openapi-fetch";

import type { paths } from "./schema";

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
  const api = createClient<paths>({
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
    headers: { Authorization: `Bearer ${accessToken}` },
  });
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
