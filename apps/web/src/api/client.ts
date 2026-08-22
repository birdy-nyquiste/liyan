import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { components } from "./schema";

export type SourceInput = components["schemas"]["SourceInput"];
export type PreparedSourceResponse = components["schemas"]["PrepareSourceResponse"];
export type TaskSummaryResponse = components["schemas"]["TaskSummary"];
export type UrlSourceResponse = components["schemas"]["UrlSourceResponse"];
export type FileSourceResponse = components["schemas"]["FileSourceResponse"];
export type SessionSourceResponse = components["schemas"]["SessionSourceResponse"];
export type TaskCreationSessionResponse = components["schemas"]["TaskCreationSessionResponse"];

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
    body: {
      idempotency_key: idempotencyKey,
      source,
      source_ids: [],
      accepted_warning_versions: {},
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.task;
}

export async function confirmTaskCreationSession(
  accessToken: string,
  idempotencyKey: string,
  clientSessionId: string,
  sourceIds: string[],
  acceptedWarningVersions: Record<string, number>,
): Promise<TaskSummaryResponse> {
  const result = await authenticatedApi(accessToken).POST("/task-creation/confirm", {
    body: {
      idempotency_key: idempotencyKey,
      client_session_id: clientSessionId,
      source_ids: sourceIds,
      accepted_warning_versions: acceptedWarningVersions,
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.task;
}

export async function getTaskCreationSession(
  accessToken: string,
  clientSessionId: string,
): Promise<TaskCreationSessionResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/sessions/{client_session_id}",
    { params: { path: { client_session_id: clientSessionId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function createPastedSource(
  accessToken: string,
  clientSessionId: string,
  clientSourceId: string,
  source: SourceInput,
): Promise<SessionSourceResponse> {
  const result = await authenticatedApi(accessToken).POST("/task-creation/pasted-sources", {
    body: {
      client_session_id: clientSessionId,
      client_source_id: clientSourceId,
      ...source,
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function editPastedSource(
  accessToken: string,
  sourceId: string,
  source: SourceInput,
): Promise<SessionSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/pasted-sources/{source_id}",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function deleteTaskCreationSource(
  accessToken: string,
  sourceId: string,
): Promise<void> {
  const result = await authenticatedApi(accessToken).DELETE(
    "/task-creation/sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.response.ok) throw new ApiError(result.response.status);
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

export async function createUrlSource(
  accessToken: string,
  clientSessionId: string,
  clientSourceId: string,
  url: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).POST("/task-creation/url-sources", {
    body: {
      client_session_id: clientSessionId,
      client_source_id: clientSourceId,
      url,
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getUrlSource(
  accessToken: string,
  sourceId: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/url-sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function retryUrlSource(
  accessToken: string,
  sourceId: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/task-creation/url-sources/{source_id}/retry",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function replaceUrlSource(
  accessToken: string,
  sourceId: string,
  url: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).PUT(
    "/task-creation/url-sources/{source_id}",
    { params: { path: { source_id: sourceId } }, body: { url } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function editUrlSourceContent(
  accessToken: string,
  sourceId: string,
  source: SourceInput,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/url-sources/{source_id}/content",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function cancelExecution(
  accessToken: string,
  executionId: string,
): Promise<void> {
  const result = await authenticatedApi(accessToken).POST(
    "/executions/{execution_id}/cancel",
    { params: { path: { execution_id: executionId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
}

export async function createFileSource(
  accessToken: string,
  clientSessionId: string,
  clientSourceId: string,
  file: File,
): Promise<FileSourceResponse> {
  const form = new FormData();
  form.set("client_session_id", clientSessionId);
  form.set("client_source_id", clientSourceId);
  form.set("file", file);
  const result = await authenticatedApi(accessToken).POST("/task-creation/file-sources", {
    body: {
      client_session_id: clientSessionId,
      client_source_id: clientSourceId,
      file: file.name,
    },
    bodySerializer: () => form,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getFileSource(
  accessToken: string,
  sourceId: string,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/file-sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function replaceFileSource(
  accessToken: string,
  sourceId: string,
  file: File,
): Promise<FileSourceResponse> {
  const form = new FormData();
  form.set("file", file);
  const result = await authenticatedApi(accessToken).PUT(
    "/task-creation/file-sources/{source_id}",
    {
      params: { path: { source_id: sourceId } },
      body: { file: file.name },
      bodySerializer: () => form,
    },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function retryFileSource(
  accessToken: string,
  sourceId: string,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/task-creation/file-sources/{source_id}/retry",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function editFileSourceContent(
  accessToken: string,
  sourceId: string,
  source: SourceInput,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/file-sources/{source_id}/content",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}
