import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { components } from "./schema";

export type SourceInput = components["schemas"]["SourceInput"];
export type TaskSummaryResponse = components["schemas"]["TaskSummary"];
export type UrlSourceResponse = components["schemas"]["UrlSourceResponse"];
export type FileSourceResponse = components["schemas"]["FileSourceResponse"];
export type SessionSourceResponse = components["schemas"]["SessionSourceResponse"];
export type TaskCreationSessionResponse = components["schemas"]["TaskCreationSessionResponse"];
export type ZhiyanStateResponse = components["schemas"]["ZhiyanStateResponse"];
export type TaskVersionZhiyanResponse = components["schemas"]["TaskVersionZhiyanResponse"];
export type TaskVersionHistory = components["schemas"]["TaskVersionHistory"];
export type TaskVersionSnapshot = components["schemas"]["TaskVersionSnapshot"];
export type VersionSource = components["schemas"]["VersionSource"];
export type SourceEditSessionResponse = components["schemas"]["SourceEditSessionResponse"];
export type SaveSourceEditRequest = components["schemas"]["SaveSourceEditRequest"];
export type LiyanStateResponse = components["schemas"]["LiyanStateResponse"];
export type StartLiyanRunRequest = components["schemas"]["StartLiyanRunRequest"];
export type LiyanRevisionResponse = components["schemas"]["LiyanRevisionResponse"];
export type SaveLiyanRevisionRequest = components["schemas"]["SaveLiyanRevisionRequest"];
export type InstructionDocument = components["schemas"]["InstructionDocument"];
export type InstructionCapsule = components["schemas"]["InstructionCapsule"];
export type PublicationTargetResponse = components["schemas"]["PublicationTargetResponse"];
export type EligibleArticleResponse = components["schemas"]["EligibleArticleResponse"];
export type PublishTaskResponse = components["schemas"]["PublishTaskResponse"];

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

export async function getTaskZhiyan(
  accessToken: string,
  taskId: string,
): Promise<TaskVersionZhiyanResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/zhiyan", {
    params: { path: { task_id: taskId } },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getTaskVersionZhiyan(
  accessToken: string,
  taskId: string,
  versionId: string,
): Promise<TaskVersionZhiyanResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/tasks/{task_id}/versions/{version_id}/zhiyan",
    { params: { path: { task_id: taskId, version_id: versionId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function listTaskVersions(
  accessToken: string,
  taskId: string,
): Promise<TaskVersionHistory> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/versions", {
    params: { path: { task_id: taskId } },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function createSourceEditSession(
  accessToken: string,
  taskId: string,
): Promise<SourceEditSessionResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/tasks/{task_id}/source-edit-sessions",
    { params: { path: { task_id: taskId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function saveSourceEditSession(
  accessToken: string,
  editSessionId: string,
  request: SaveSourceEditRequest,
): Promise<TaskVersionSnapshot> {
  const result = await authenticatedApi(accessToken).POST(
    "/source-edit-sessions/{edit_id}/save",
    { params: { path: { edit_id: editSessionId } }, body: request },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function discardSourceEditSession(
  accessToken: string,
  editSessionId: string,
  keepalive = false,
): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  const response = await fetch(new Request(
    `${baseUrl}/source-edit-sessions/${editSessionId}/discard`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${accessToken}` },
      keepalive,
    },
  ));
  if (!response.ok) throw new ApiError(response.status);
}

export async function restoreTaskVersion(
  accessToken: string,
  taskId: string,
  versionId: string,
  idempotencyKey: string,
): Promise<TaskVersionSnapshot> {
  const result = await authenticatedApi(accessToken).POST(
    "/tasks/{task_id}/versions/{version_id}/restore",
    {
      params: { path: { task_id: taskId, version_id: versionId } },
      body: { idempotency_key: idempotencyKey },
    },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function startZhiyanRun(
  accessToken: string,
  sourceRevisionId: string,
): Promise<ZhiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/source-revisions/{source_revision_id}/zhiyan-runs",
    { params: { path: { source_revision_id: sourceRevisionId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getTaskLiyan(
  accessToken: string,
  taskId: string,
  workingCopyHash: string | null = null,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/liyan", {
    params: {
      path: { task_id: taskId },
      query: workingCopyHash ? { working_copy_hash: workingCopyHash } : {},
    },
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function saveLiyanRevision(
  accessToken: string,
  taskId: string,
  request: SaveLiyanRevisionRequest,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST("/tasks/{task_id}/liyan-revisions", {
    params: { path: { task_id: taskId } },
    body: request,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function restoreLiyanRevision(
  accessToken: string,
  taskId: string,
  revisionId: string,
  idempotencyKey: string,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/tasks/{task_id}/liyan-revisions/{revision_id}/restore",
    {
      params: { path: { task_id: taskId, revision_id: revisionId } },
      body: { idempotency_key: idempotencyKey },
    },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function startLiyanRun(
  accessToken: string,
  taskId: string,
  request: StartLiyanRunRequest,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST("/tasks/{task_id}/liyan-runs", {
    params: { path: { task_id: taskId } },
    body: request,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function listPublicationTargets(
  accessToken: string,
): Promise<PublicationTargetResponse[]> {
  const result = await authenticatedApi(accessToken).GET("/publication/targets");
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.items;
}

export async function listEligibleArticles(
  accessToken: string,
): Promise<EligibleArticleResponse[]> {
  const result = await authenticatedApi(accessToken).GET("/publication/eligible-articles");
  if (!result.data) throw new ApiError(result.response.status);
  return result.data.items;
}

export async function confirmPublication(
  accessToken: string,
  request: {
    idempotency_key: string;
    task_id: string;
    revision_id: string;
    target_key: string;
    working_copy_hash: string | null;
  },
): Promise<PublishTaskResponse> {
  const result = await authenticatedApi(accessToken).POST("/publication/publish-tasks", {
    body: request,
  });
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

export async function getPublishTask(
  accessToken: string,
  publishTaskId: string,
): Promise<PublishTaskResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/publication/publish-tasks/{publish_task_id}",
    { params: { path: { publish_task_id: publishTaskId } } },
  );
  if (!result.data) throw new ApiError(result.response.status);
  return result.data;
}

