import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  confirmPublication,
  getPublishTask,
  listPublicationTargets,
  type PublicationTargetResponse,
  type PublishTaskResponse,
} from "../api/client";
import { ArticleReader } from "./ArticleReader";

const DEFAULT_POLL_INTERVAL_MS = 2000;
const CONFLICT = 409;

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
 * Everything here is read-only on purpose. The title and body shown are the
 * ones the server will lock, and changing them means going back to editing and
 * saving another Revision — a confirmation screen that could edit would make
 * "what was submitted" unanswerable.
 */
export function PublicationConfirmation({
  accessToken,
  article,
  workingCopyHash = null,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  onClose,
}: {
  accessToken: string;
  article: PublicationArticle;
  workingCopyHash?: string | null;
  pollIntervalMs?: number;
  onClose(): void;
}) {
  const [targets, setTargets] = useState<PublicationTargetResponse[] | null>(null);
  const [targetKey, setTargetKey] = useState<string | null>(null);
  const [publishTask, setPublishTask] = useState<PublishTaskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [polls, setPolls] = useState(0);
  const idempotencyKey = useRef(crypto.randomUUID());

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
    } catch {
      setError("发布任务加载失败，请稍后重试。");
    } finally {
      setPolls((count) => count + 1);
    }
  }, [accessToken]);

  const pending = publishTask?.status === "pending";
  useEffect(() => {
    if (!pending || !publishTask) return;
    const timer = setTimeout(() => void refresh(publishTask.id), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [pending, publishTask, pollIntervalMs, polls, refresh]);

  async function confirm() {
    if (!targetKey) return;
    setBusy(true);
    try {
      setPublishTask(
        await confirmPublication(accessToken, {
          idempotency_key: idempotencyKey.current,
          task_id: article.taskId,
          revision_id: article.revisionId,
          target_key: targetKey,
          working_copy_hash: workingCopyHash,
        }),
      );
      setError(null);
    } catch (thrown) {
      setError(
        thrown instanceof ApiError && thrown.status === CONFLICT
          ? "该文章已不可发布，请保存最新 Revision 后重试。"
          : "发布未能提交，请稍后重试。",
      );
    } finally {
      setBusy(false);
    }
  }

  const selected = targets?.find((target) => target.key === targetKey) ?? null;
  const confirmed = publishTask !== null;

  return (
    <section className="publication-confirmation" aria-labelledby="publication-confirm-heading">
      <h3 id="publication-confirm-heading">确认发布</h3>

      <dl className="publication-locked">
        <div>
          <dt>立言任务</dt>
          <dd>{article.taskLabel}</dd>
        </div>
        <div>
          <dt>文章 Revision</dt>
          <dd>Revision {article.revisionNumber}</dd>
        </div>
        <div>
          <dt>标题</dt>
          <dd>{article.title}</dd>
        </div>
        <div>
          <dt>作者</dt>
          <dd>{selected ? selected.author : "选择发布目标后确定"}</dd>
        </div>
        <div>
          <dt>发布目标</dt>
          <dd>{selected ? `${selected.display_name}（${selected.site_url}）` : "尚未选择"}</dd>
        </div>
      </dl>

      {!confirmed && targets && targets.length > 1 ? (
        <label className="field">
          <span>发布目标</span>
          <select
            value={targetKey ?? ""}
            disabled={busy}
            onChange={(event) => setTargetKey(event.target.value || null)}
          >
            <option value="">请选择</option>
            {targets.map((target) => (
              <option key={target.key} value={target.key}>
                {target.display_name}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {targets && targets.length === 0 ? (
        <p role="status" className="form-hint">当前没有可用的发布目标。</p>
      ) : null}

      <p className="form-hint">确认页只能预览。要修改标题或正文，请返回编辑并保存新的 Revision。</p>
      <ArticleReader
        label={`Revision ${article.revisionNumber} 发布正文`}
        bodyMarkdown={article.bodyMarkdown}
      />

      {error ? <p role="alert" className="form-error">{error}</p> : null}

      {publishTask ? (
        <div className="publication-result">
          <p role="status">{STATUS_TEXT[publishTask.status]}</p>
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
                是否在 Blog 上公开发布，由你在 Blog 决定；立言阁不再参与。
                本次发布不会结束这项立言任务，你可以继续修改文章。
              </p>
            </>
          ) : null}
          {publishTask.status === "failed" && publishTask.failure_message ? (
            <p role="alert" className="form-error">{publishTask.failure_message}</p>
          ) : null}
          {publishTask.status === "outcome_unknown" ? (
            <p role="alert" className="form-error">
              {publishTask.failure_message ??
                "本次提交结果未知，立言阁不会重发；请到 Blog 查看后再决定。"}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="button-row">
        {!confirmed ? (
          <button
            className="button"
            type="button"
            disabled={busy || !targetKey}
            onClick={() => void confirm()}
          >
            确认发布
          </button>
        ) : null}
        <button className="button button--quiet" type="button" onClick={onClose}>
          {confirmed ? "关闭" : "取消"}
        </button>
      </div>
    </section>
  );
}
