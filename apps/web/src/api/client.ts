import createClient from "openapi-fetch";

import type { paths } from "./schema";
import type { components } from "./schema";

export type SourceInput = components["schemas"]["SourceInput"];
export type TaskSummaryResponse = components["schemas"]["TaskSummary"];
export type TaskListResponse = components["schemas"]["TaskListResponse"];
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
export type EligibleArticleListResponse = components["schemas"]["EligibleArticleListResponse"];
export type PublishTaskResponse = components["schemas"]["PublishTaskResponse"];
export type PublishTaskListResponse = components["schemas"]["PublishTaskListResponse"];
export type ConfirmPublicationRequest = components["schemas"]["ConfirmPublicationRequest"];
export type AccountResponse = components["schemas"]["AccountResponse"];
export type UsageEntry = components["schemas"]["UsageEntry"];
export type UsageResponse = components["schemas"]["UsageResponse"];
export type CreditPack = components["schemas"]["CreditPackResponse"];

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string | null = null,
    /** Seconds the server told us to wait, when it owns the timing. */
    public readonly retryAfterSeconds: number | null = null,
  ) {
    super(`API request failed with status ${status}.`);
  }
}

/** An ApiError carrying whatever the server said, when the message is the point. */
function refusalOf(result: { error?: unknown; response: Response }): ApiError {
  const error = result.error as { detail?: unknown } | undefined;
  const retryAfter = Number(result.response.headers.get("Retry-After"));
  return new ApiError(
    result.response.status,
    typeof error?.detail === "string" ? error.detail : null,
    Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  );
}

/**
 * The refusal to show when the server refused for a reason only it can see.
 *
 * Two different 429s reach the workbench. One is retry timing the server owns
 * (知言 and 立言 backoff), which carries `Retry-After` and is already shown as a
 * countdown beside the button — a message would say the same thing twice. The
 * other is the per-user ceiling on work in flight, which carries no timing
 * because the wait is "until one of your own runs finishes". That one has
 * nothing else to display it, so its message is the only thing the user gets,
 * and swallowing it leaves a button that does nothing when pressed.
 */
export function refusalWithoutTiming(thrown: unknown): string | null {
  if (!(thrown instanceof ApiError)) return null;
  // 402 是额度不足或来源类型未解锁。两者都没有 Retry-After，因为等待改变不了
  // 什么 — 补救办法是购买，而这句话是唯一说出这一点的东西。A generic
  // "something went wrong" here would send a user to support instead.
  if (thrown.status === 402) return thrown.detail;
  if (thrown.status !== 429 || thrown.retryAfterSeconds !== null) return null;
  return thrown.detail;
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

export async function loadTaskWorkspace(accessToken: AccessToken) {
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

export async function listTasks(accessToken: AccessToken): Promise<TaskSummaryResponse[]> {
  return (await listTaskPage(accessToken)).items;
}

export async function listTaskPage(
  accessToken: AccessToken,
  cursor: string | null = null,
): Promise<TaskListResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks", {
    params: { query: { cursor: cursor ?? undefined, limit: 20 } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getTask(
  accessToken: AccessToken,
  taskId: string,
): Promise<TaskSummaryResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}", {
    params: { path: { task_id: taskId } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getAccount(accessToken: AccessToken): Promise<AccountResponse> {
  const result = await authenticatedApi(accessToken).GET("/account", {});
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function listAccountUsage(
  accessToken: AccessToken,
  offset = 0,
): Promise<UsageResponse> {
  const result = await authenticatedApi(accessToken).GET("/account/usage", {
    params: { query: { offset } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function listCreditPacks(accessToken: AccessToken): Promise<CreditPack[]> {
  const result = await authenticatedApi(accessToken).GET("/account/credit-packs", {});
  if (!result.data) throw refusalOf(result);
  return result.data.packs;
}

/**
 * Open a Stripe Checkout Session and answer with where to send the user.
 *
 * The Price is all that goes up. What it buys is decided on the server, from a
 * mapping the client never sees — `docs/operations/credits.md` is explicit that
 * the 额度 amount may never come from anything a client could have influenced.
 */
export async function createCheckoutSession(
  accessToken: AccessToken,
  priceId: string,
): Promise<string> {
  const result = await authenticatedApi(accessToken).POST("/account/checkout-session", {
    body: { price_id: priceId },
  });
  if (!result.data) throw refusalOf(result);
  return result.data.url;
}

/**
 * Where a request gets its bearer token.
 *
 * A string is a token frozen at the moment it was read. That is what the
 * workbench used to thread through every component, and it is why a tab left
 * open for an hour began refusing everything: Supabase access tokens expire,
 * supabase-js quietly refreshed the session in the background, and nothing
 * ever read the new token. Every call then failed with whatever message the
 * caller had for its own operation — "立言生成未能启动" for an expired login.
 *
 * A function is asked again for every single request, so the token that goes
 * out is the one the session holds now. Sign-in passes one of those; a plain
 * string remains accepted because a test that means one fixed token should be
 * able to say so.
 */
export type AccessToken = string | (() => Promise<string | null>);

/** Told when the server refuses a request because the session is no longer good. */
type SessionExpiredListener = () => void;
const sessionExpiredListeners = new Set<SessionExpiredListener>();

/**
 * Hear about a 401 from anywhere in the workbench.
 *
 * A refused request surfaces wherever it was made, and every caller there has
 * its own sentence for its own failure — none of which is "your login ran
 * out". Returning to sign-in is a whole-application decision, so it is made
 * once, here, rather than by each panel guessing at it.
 */
export function onSessionExpired(listener: SessionExpiredListener): () => void {
  sessionExpiredListeners.add(listener);
  return () => sessionExpiredListeners.delete(listener);
}

function announceSessionExpired(): void {
  for (const listener of sessionExpiredListeners) listener();
}

async function bearerToken(accessToken: AccessToken): Promise<string | null> {
  return typeof accessToken === "string" ? accessToken : await accessToken();
}

function authenticatedApi(accessToken: AccessToken) {
  const api = createClient<paths>({
    baseUrl: import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
  });
  api.use({
    async onRequest({ request }) {
      const token = await bearerToken(accessToken);
      // No token at all is the session having ended while the workbench was
      // still open. Answering 401 here rather than sending the request
      // unsigned gives the caller the same refusal the server would have, but
      // the announcement has to be made explicitly: returning a Response from
      // `onRequest` short-circuits the request, and `onResponse` does not run
      // for one that never went out.
      if (!token) {
        announceSessionExpired();
        return new Response(null, { status: 401 });
      }
      request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
    onResponse({ response }) {
      if (response.status === 401) announceSessionExpired();
    },
  });
  return api;
}

export async function confirmTaskCreationSession(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data.task;
}

export async function getTaskCreationSession(
  accessToken: AccessToken,
  clientSessionId: string,
): Promise<TaskCreationSessionResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/sessions/{client_session_id}",
    { params: { path: { client_session_id: clientSessionId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function createPastedSource(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function editPastedSource(
  accessToken: AccessToken,
  sourceId: string,
  source: SourceInput,
): Promise<SessionSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/pasted-sources/{source_id}",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function deleteTaskCreationSource(
  accessToken: AccessToken,
  sourceId: string,
): Promise<void> {
  const result = await authenticatedApi(accessToken).DELETE(
    "/task-creation/sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.response.ok) throw refusalOf(result);
}

export async function renameTask(
  accessToken: AccessToken,
  taskId: string,
  displayName: string,
): Promise<TaskSummaryResponse> {
  const result = await authenticatedApi(accessToken).PATCH("/tasks/{task_id}", {
    params: { path: { task_id: taskId } },
    body: { display_name: displayName },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function deleteTask(accessToken: AccessToken, taskId: string): Promise<void> {
  const result = await authenticatedApi(accessToken).DELETE("/tasks/{task_id}", {
    params: { path: { task_id: taskId } },
    body: { confirmed: true },
  });
  if (!result.response.ok) {
    const error = result.error as { detail?: unknown } | undefined;
    throw new ApiError(
      result.response.status,
      typeof error?.detail === "string" ? error.detail : null,
    );
  }
}

export async function createUrlSource(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getUrlSource(
  accessToken: AccessToken,
  sourceId: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/url-sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function retryUrlSource(
  accessToken: AccessToken,
  sourceId: string,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/task-creation/url-sources/{source_id}/retry",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function editUrlSourceContent(
  accessToken: AccessToken,
  sourceId: string,
  source: SourceInput,
): Promise<UrlSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/url-sources/{source_id}/content",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function cancelExecution(
  accessToken: AccessToken,
  executionId: string,
): Promise<void> {
  const result = await authenticatedApi(accessToken).POST(
    "/executions/{execution_id}/cancel",
    { params: { path: { execution_id: executionId } } },
  );
  if (!result.data) throw refusalOf(result);
}

export async function createFileSource(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getFileSource(
  accessToken: AccessToken,
  sourceId: string,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/task-creation/file-sources/{source_id}",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function retryFileSource(
  accessToken: AccessToken,
  sourceId: string,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/task-creation/file-sources/{source_id}/retry",
    { params: { path: { source_id: sourceId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function editFileSourceContent(
  accessToken: AccessToken,
  sourceId: string,
  source: SourceInput,
): Promise<FileSourceResponse> {
  const result = await authenticatedApi(accessToken).PATCH(
    "/task-creation/file-sources/{source_id}/content",
    { params: { path: { source_id: sourceId } }, body: source },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getTaskZhiyan(
  accessToken: AccessToken,
  taskId: string,
): Promise<TaskVersionZhiyanResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/zhiyan", {
    params: { path: { task_id: taskId } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getTaskVersionZhiyan(
  accessToken: AccessToken,
  taskId: string,
  versionId: string,
): Promise<TaskVersionZhiyanResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/tasks/{task_id}/versions/{version_id}/zhiyan",
    { params: { path: { task_id: taskId, version_id: versionId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function listTaskVersions(
  accessToken: AccessToken,
  taskId: string,
): Promise<TaskVersionHistory> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/versions", {
    params: { path: { task_id: taskId } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function createSourceEditSession(
  accessToken: AccessToken,
  taskId: string,
): Promise<SourceEditSessionResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/tasks/{task_id}/source-edit-sessions",
    { params: { path: { task_id: taskId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function saveSourceEditSession(
  accessToken: AccessToken,
  editSessionId: string,
  request: SaveSourceEditRequest,
): Promise<TaskVersionSnapshot> {
  const result = await authenticatedApi(accessToken).POST(
    "/source-edit-sessions/{edit_id}/save",
    { params: { path: { edit_id: editSessionId } }, body: request },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function discardSourceEditSession(
  accessToken: AccessToken,
  editSessionId: string,
  keepalive = false,
): Promise<void> {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
  // Hand-rolled rather than through `authenticatedApi`, because `keepalive` is
  // what lets this survive the page it was sent from — so the token has to be
  // resolved here too, and the 401 reported by the same route as every other.
  const token = await bearerToken(accessToken);
  if (!token) {
    announceSessionExpired();
    throw new ApiError(401);
  }
  const response = await fetch(new Request(
    `${baseUrl}/source-edit-sessions/${editSessionId}/discard`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      keepalive,
    },
  ));
  if (response.status === 401) announceSessionExpired();
  if (!response.ok) throw new ApiError(response.status);
}

export async function restoreTaskVersion(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function startZhiyanRun(
  accessToken: AccessToken,
  sourceRevisionId: string,
): Promise<ZhiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/source-revisions/{source_revision_id}/zhiyan-runs",
    { params: { path: { source_revision_id: sourceRevisionId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getTaskLiyan(
  accessToken: AccessToken,
  taskId: string,
  workingCopyHash: string | null = null,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).GET("/tasks/{task_id}/liyan", {
    params: {
      path: { task_id: taskId },
      query: workingCopyHash ? { working_copy_hash: workingCopyHash } : {},
    },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function saveLiyanRevision(
  accessToken: AccessToken,
  taskId: string,
  request: SaveLiyanRevisionRequest,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST("/tasks/{task_id}/liyan-revisions", {
    params: { path: { task_id: taskId } },
    body: request,
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function restoreLiyanRevision(
  accessToken: AccessToken,
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
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function startLiyanRun(
  accessToken: AccessToken,
  taskId: string,
  request: StartLiyanRunRequest,
): Promise<LiyanStateResponse> {
  const result = await authenticatedApi(accessToken).POST("/tasks/{task_id}/liyan-runs", {
    params: { path: { task_id: taskId } },
    body: request,
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function listPublicationTargets(
  accessToken: AccessToken,
): Promise<PublicationTargetResponse[]> {
  const result = await authenticatedApi(accessToken).GET("/publication/targets");
  if (!result.data) throw refusalOf(result);
  return result.data.items;
}

export async function listEligibleArticles(
  accessToken: AccessToken,
): Promise<EligibleArticleResponse[]> {
  return (await listEligibleArticlePage(accessToken)).items;
}

export async function listEligibleArticlePage(
  accessToken: AccessToken,
  cursor?: string | null,
): Promise<EligibleArticleListResponse> {
  const result = await authenticatedApi(accessToken).GET("/publication/eligible-articles", {
    params: { query: { cursor: cursor ?? undefined } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function confirmPublication(
  accessToken: AccessToken,
  request: ConfirmPublicationRequest,
): Promise<PublishTaskResponse> {
  const result = await authenticatedApi(accessToken).POST("/publication/publish-tasks", {
    body: request,
  });
  // The refusal text matters here: one of these answers is the warning that a
  // newer Revision would create a second Blog item, which the user must read.
  if (!result.data) throw refusalOf(result);
  return result.data;
}

/** Send the locked snapshot again. Only a definitive failure may be retried. */
export async function retryPublication(
  accessToken: AccessToken,
  publishTaskId: string,
  idempotencyKey: string,
  acknowledgeExistingPreview = false,
): Promise<PublishTaskResponse> {
  const result = await authenticatedApi(accessToken).POST(
    "/publication/publish-tasks/{publish_task_id}/retry",
    {
      params: { path: { publish_task_id: publishTaskId } },
      body: {
        idempotency_key: idempotencyKey,
        acknowledge_existing_preview: acknowledgeExistingPreview,
      },
    },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function getPublishTask(
  accessToken: AccessToken,
  publishTaskId: string,
): Promise<PublishTaskResponse> {
  const result = await authenticatedApi(accessToken).GET(
    "/publication/publish-tasks/{publish_task_id}",
    { params: { path: { publish_task_id: publishTaskId } } },
  );
  if (!result.data) throw refusalOf(result);
  return result.data;
}

export async function listPublishTasks(accessToken: AccessToken): Promise<PublishTaskResponse[]> {
  return (await listPublishTaskPage(accessToken)).items;
}

export async function listPublishTaskPage(
  accessToken: AccessToken,
  cursor?: string | null,
): Promise<PublishTaskListResponse> {
  const result = await authenticatedApi(accessToken).GET("/publication/publish-tasks", {
    params: { query: { cursor: cursor ?? undefined } },
  });
  if (!result.data) throw refusalOf(result);
  return result.data;
}
