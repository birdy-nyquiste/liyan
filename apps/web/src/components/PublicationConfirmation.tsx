import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  confirmPublication,
  getPublishTask,
  listPublicationTargets,
  refusalWithoutTiming,
  retryPublication,
  type PublicationTargetResponse,
  type PublishTaskResponse,
  type AccessToken,
} from "../api/client";
import { ArticleReader } from "./ArticleReader";
import { useInterfaceLocale } from "../interfaceLocale";
import {
  EXISTING_PREVIEW_WARNING,
  PRECONDITION_FAILED,
  RETRY_FAILED,
} from "./publicationMessages";
import { EXECUTION_POLL_MS } from "./pollIntervals";

const CONFLICT = 409;
const AUTHOR_LIMIT = 100;
const AUTHOR_KEY = "liyan:publication-author:v1";

/** The last author name this browser used, offered so it needn't be retyped. */
function rememberedAuthor(userId: string): string {
  try {
    return window.localStorage.getItem(`${AUTHOR_KEY}:${encodeURIComponent(userId)}`) ?? "";
  } catch {
    return "";
  }
}

function rememberAuthor(userId: string, author: string): void {
  try {
    window.localStorage.setItem(`${AUTHOR_KEY}:${encodeURIComponent(userId)}`, author);
  } catch {
    // Browser storage can be unavailable. Publishing must remain usable.
  }
}

/** What both entries hand the confirmation: one saved, eligible Revision. */
export type PublicationArticle = {
  taskId: string;
  taskLabel: string;
  revisionId: string;
  revisionNumber: number;
  title: string;
  bodyMarkdown: string;
};

const STATUS_TEXT: Record<PublishTaskResponse["status"], string> = {
  pending: "正在提交到 Blog……",
  succeeded: "Blog 已创建 Preview。",
  failed: "本次提交失败。",
  outcome_unknown: "本次提交结果未知。",
};

/**
 * 确认发布: the one flow both the article and the publication center reach.
 *
 * The article is read-only on purpose. The title and body shown are the ones
 * the server will lock, and changing them means going back to editing and
 * saving another Revision — a confirmation screen that could edit the article
 * would make "what was submitted" unanswerable.
 *
 * The author is the one field the user fills in. Blog needs a display name and
 * treats one name as one author across submissions, so it belongs to whoever is
 * publishing rather than to the destination.
 */
export function PublicationConfirmation({
  userId,
  accessToken,
  article,
  workingCopyHash = null,
  pollIntervalMs = EXECUTION_POLL_MS,
  onStatusChange,
  onClose,
}: {
  userId: string;
  accessToken: AccessToken;
  article: PublicationArticle;
  workingCopyHash?: string | null;
  pollIntervalMs?: number;
  onStatusChange?(): void;
  onClose(): void;
}) {
  const { locale, t, domainMessage } = useInterfaceLocale();
  const [targets, setTargets] = useState<PublicationTargetResponse[] | null>(null);
  const [targetKey, setTargetKey] = useState<string | null>(null);
  const [author, setAuthor] = useState(() => rememberedAuthor(userId));
  const [publishTask, setPublishTask] = useState<PublishTaskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  /**
   * A warning is a question, so it carries the answer's action with it.
   *
   * Both confirming and retrying can raise the same warning, and pressing on
   * means something different for each. Holding the continuation here keeps
   * the button from having to work out which one it is.
   */
  const [warning, setWarning] = useState<{ message: string; proceed(): Promise<void> } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [polls, setPolls] = useState(0);
  const idempotencyKey = useRef(crypto.randomUUID());
  const retryKey = useRef(crypto.randomUUID());

  useEffect(() => {
    let active = true;
    void listPublicationTargets(accessToken)
      .then((items) => {
        if (!active) return;
        setTargets(items);
        // A sole authorized destination is not a decision worth asking for.
        if (items.length === 1) setTargetKey(items[0].key);
      })
      .catch(() => {
        if (active) setError("发布目标加载失败，请稍后重试。");
      });
    return () => {
      active = false;
    };
  }, [accessToken]);

  const refresh = useCallback(async (publishTaskId: string) => {
    try {
      setPublishTask(await getPublishTask(accessToken, publishTaskId));
      onStatusChange?.();
    } catch {
      setError("发布任务加载失败，请稍后重试。");
    } finally {
      setPolls((count) => count + 1);
    }
  }, [accessToken, onStatusChange]);

  const pending = publishTask?.status === "pending";
  useEffect(() => {
    if (!pending || !publishTask) return;
    const timer = setTimeout(() => void refresh(publishTask.id), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [pending, publishTask, pollIntervalMs, polls, refresh]);

  /**
   * Confirm, and stop at the warning the first time the server raises one.
   *
   * `acknowledged` is only ever true because the user read the warning and
   * pressed on. Nothing else sets it, so a second Blog item cannot be created
   * by a stray click or a retried request.
   */
  async function confirm(acknowledged = false) {
    const name = author.trim();
    if (!targetKey || !name) return;
    setBusy(true);
    try {
      const confirmedTask = await confirmPublication(accessToken, {
          idempotency_key: idempotencyKey.current,
          task_id: article.taskId,
          revision_id: article.revisionId,
          target_key: targetKey,
          author: name,
          working_copy_hash: workingCopyHash,
          acknowledge_existing_preview: acknowledged,
        });
      setPublishTask(confirmedTask);
      onStatusChange?.();
      rememberAuthor(userId, name);
      setError(null);
      setWarning(null);
    } catch (thrown) {
      if (thrown instanceof ApiError && thrown.status === PRECONDITION_FAILED) {
        setWarning({
          message: thrown.detail ?? EXISTING_PREVIEW_WARNING,
          proceed: () => confirm(true),
        });
        return;
      }
      setError(
        refusalWithoutTiming(thrown) ??
          (thrown instanceof ApiError && thrown.status === CONFLICT
            ? (thrown.detail ?? "该文章已不可发布，请保存最新 Revision 后重试。")
            : "发布未能提交，请稍后重试。"),
      );
    } finally {
      setBusy(false);
    }
  }

  /**
   * Send the same snapshot again after a definitive failure.
   *
   * The button exists only for `failed`, because that is the one outcome that
   * proves nothing was created. 结果未知 gets no such affordance by design.
   */
  async function retry(acknowledged = false) {
    if (!publishTask) return;
    setBusy(true);
    try {
      setPublishTask(
        await retryPublication(accessToken, publishTask.id, retryKey.current, acknowledged),
      );
      onStatusChange?.();
      setError(null);
      setWarning(null);
    } catch (thrown) {
      if (thrown instanceof ApiError && thrown.status === PRECONDITION_FAILED) {
        setWarning({
          message: thrown.detail ?? EXISTING_PREVIEW_WARNING,
          proceed: () => retry(true),
        });
        return;
      }
      setError(
        refusalWithoutTiming(thrown) ??
          (thrown instanceof ApiError && thrown.detail ? thrown.detail : RETRY_FAILED),
      );
    } finally {
      setBusy(false);
    }
  }

  const selected = targets?.find((target) => target.key === targetKey) ?? null;
  const confirmed = publishTask !== null;

  return (
    <section className="publication-confirmation" aria-labelledby="publication-confirm-heading">
      {/* The 立言 pane and the publication page both title this region before
          reaching it; the heading stays as the region's name rather than
          printing 确认发布 twice, one line apart. */}
      <h3 className="sr-only" id="publication-confirm-heading">{t("确认发布")}</h3>

      <dl className="publication-locked">
        <div>
          <dt>{t("立言任务")}</dt>
          <dd>{article.taskLabel}</dd>
        </div>
        <div>
          <dt>{t("文章草稿")}</dt>
          <dd>{t("草稿")} {article.revisionNumber}</dd>
        </div>
        <div>
          <dt>{t("标题")}</dt>
          <dd>{article.title}</dd>
        </div>
        <div>
          <dt>{t("作者")}</dt>
          <dd>{confirmed ? publishTask?.author : author.trim() || t("尚未填写")}</dd>
        </div>
        <div>
          <dt>{t("发布目标")}</dt>
          <dd>{selected
            ? locale === "en"
              ? `${selected.display_name} (${selected.site_url})`
              : `${selected.display_name}（${selected.site_url}）`
            : t("尚未选择")}</dd>
        </div>
      </dl>

      {!confirmed ? (
        <label className="field">
          <span>{t("作者（显示在 Blog 上）")}</span>
          <input
            type="text"
            value={author}
            maxLength={AUTHOR_LIMIT}
            disabled={busy}
            required
            onChange={(event) => setAuthor(event.target.value)}
          />
        </label>
      ) : null}
      {!confirmed && targets && targets.length > 1 ? (
        <label className="field">
          <span>{t("发布目标")}</span>
          <select
            value={targetKey ?? ""}
            disabled={busy}
            onChange={(event) => setTargetKey(event.target.value || null)}
          >
            <option value="">{t("请选择")}</option>
            {targets.map((target) => (
              <option key={target.key} value={target.key}>
                {target.display_name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {targets && targets.length === 0 ? (
        <p role="status" className="form-hint">{t("当前没有可用的发布目标。")}</p>
      ) : null}

      <p className="form-hint">{t("确认页只能预览。要修改标题或正文，请返回编辑并保存新草稿。")}</p>
      <ArticleReader
        label={`${t("草稿")} ${article.revisionNumber} ${t("文章正文")}`}
        bodyMarkdown={article.bodyMarkdown}
      />

      {error ? <p role="alert" className="form-error">{domainMessage(error)}</p> : null}

      {warning ? (
        <div className="publication-warning">
          <p role="alert" className="form-error">{domainMessage(warning.message)}</p>
          <button
            className="button"
            type="button"
            disabled={busy}
            onClick={() => void warning.proceed()}
          >
            {t("仍要发布")}
          </button>
        </div>
      ) : null}

      {publishTask ? (
        <div className="publication-result">
          <p role="status">{t(STATUS_TEXT[publishTask.status])}</p>
          {publishTask.status === "succeeded" && publishTask.preview_url ? (
            <>
              <a
                className="publication-preview-link"
                href={publishTask.preview_url}
                target="_blank"
                rel="noreferrer"
              >
                {publishTask.preview_url}
              </a>
              {/* 立言阁 stops here: what happens to the Preview in Blog is the
                  user's to decide, and the product claims nothing about it. */}
              <p className="form-hint">
                {t("是否在 Blog 上公开发布，由你在 Blog 决定；立言阁不再参与。本次发布不会结束这项立言任务，你可以继续修改文章。")}
              </p>
            </>
          ) : null}
          {publishTask.status === "failed" ? (
            <>
              {publishTask.failure_message ? (
                <p role="alert" className="form-error">{domainMessage(publishTask.failure_message, publishTask.execution?.error?.code)}</p>
              ) : null}
              {/* Nothing was created, so the same snapshot may go again — and
                  only that snapshot: publishing a newer article is a new
                  confirmation, with the warning that belongs to one. */}
              <p className="form-hint">{t("Blog 没有收到内容，可以重新提交同一份快照。")}</p>
              <button
                className="button"
                type="button"
                disabled={busy}
                onClick={() => void retry()}
              >
                {t("重试本次提交")}
              </button>
            </>
          ) : null}
          {publishTask.status === "outcome_unknown" ? (
            <p role="alert" className="form-error">
              {domainMessage(
                publishTask.failure_message
                  ?? "本次提交结果未知，立言阁不会重发；请到 Blog 查看后再决定。",
                publishTask.execution?.error?.code,
              )}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="button-row">
        {!confirmed ? (
          <button
            className="button"
            type="button"
            disabled={busy || !targetKey || !author.trim()}
            onClick={() => void confirm()}
          >
            {t("确认发布")}
          </button>
        ) : null}
        <button className="button button--quiet" type="button" onClick={onClose}>
          {confirmed ? t("关闭") : t("取消")}
        </button>
      </div>
    </section>
  );
}
