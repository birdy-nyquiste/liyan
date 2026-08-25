import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  listEligibleArticlePage,
  listPublishTaskPage,
  retryPublication,
  type EligibleArticleResponse,
  type PublishTaskResponse,
} from "../api/client";
import { articleContentHash } from "./articleContentHash";
import {
  PublicationConfirmation,
  type PublicationArticle,
} from "./PublicationConfirmation";
import {
  EXISTING_PREVIEW_WARNING,
  PRECONDITION_FAILED,
  RETRY_FAILED,
} from "./publicationMessages";
import { loadWorkingCopy } from "./workingCopyStorage";

const publicationArticle = (article: EligibleArticleResponse): PublicationArticle => ({
  taskId: article.task_id,
  taskLabel: article.task_display_name,
  revisionId: article.revision_id,
  revisionNumber: article.revision_number,
  title: article.title,
  bodyMarkdown: article.body_markdown,
});

/**
 * 发布中心: pick an eligible article first, then run the same confirmation.
 *
 * The article page preselects its own Revision; here the user chooses one. Both
 * end in one flow so publication cannot acquire two behaviours.
 */
export function PublicationCenter({
  userId,
  accessToken,
  onClose,
  onPublicationChanged,
  onOpenTask,
  initialTaskId,
  initialRevisionId,
}: {
  userId: string;
  accessToken: string;
  onClose(): void;
  onPublicationChanged?(): void;
  onOpenTask?(taskId: string): void;
  initialTaskId?: string | null;
  initialRevisionId?: string | null;
}) {
  const [articles, setArticles] = useState<EligibleArticleResponse[] | null>(null);
  const [records, setRecords] = useState<PublishTaskResponse[] | null>(null);
  const [articleCursor, setArticleCursor] = useState<string | null>(null);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<EligibleArticleResponse | null>(null);
  const [draftHash, setDraftHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [warning, setWarning] = useState<{ message: string; publishTaskId: string } | null>(
    null,
  );
  const retryKeys = useRef(new Map<string, string>());

  const load = useCallback(async () => {
    try {
      const [eligible, publications] = await Promise.all([
        listEligibleArticlePage(accessToken),
        listPublishTaskPage(accessToken),
      ]);
      setArticles(eligible.items);
      setArticleCursor(eligible.next_cursor ?? null);
      setRecords(publications.items);
      setHistoryCursor(publications.next_cursor ?? null);
      setError(null);
    } catch {
      setError("发布中心加载失败，请稍后重试。");
    }
  }, [accessToken]);

  async function loadMoreArticles() {
    if (!articleCursor) return;
    const page = await listEligibleArticlePage(accessToken, articleCursor);
    setArticles((current) => [...(current ?? []), ...page.items]);
    setArticleCursor(page.next_cursor ?? null);
  }

  async function loadMoreHistory() {
    if (!historyCursor) return;
    const page = await listPublishTaskPage(accessToken, historyCursor);
    setRecords((current) => [...(current ?? []), ...page.items]);
    setHistoryCursor(page.next_cursor ?? null);
  }

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (selected || !articles || !initialTaskId || !initialRevisionId) return;
    const initial = articles.find(
      (article) => article.task_id === initialTaskId && article.revision_id === initialRevisionId,
    );
    if (initial) setSelected(initial);
  }, [articles, initialRevisionId, initialTaskId, selected]);

  /**
   * Send one failed 发布任务's snapshot again, from the record itself.
   *
   * A failure outlives the screen that produced it, so the list is where a
   * retry has to be reachable — otherwise closing the confirmation is what
   * decides whether an article can still be published.
   *
   * One 发布任务 keeps one retry key for the life of this screen, so a warning
   * cleared and resent stays the same attempt rather than becoming a second.
   */
  const resend = useCallback(
    async (publishTaskId: string, acknowledged = false) => {
      const key = retryKeys.current.get(publishTaskId) ?? crypto.randomUUID();
      retryKeys.current.set(publishTaskId, key);
      setRetrying(publishTaskId);
      try {
        await retryPublication(accessToken, publishTaskId, key, acknowledged);
        setError(null);
        setWarning(null);
        await load();
        onPublicationChanged?.();
      } catch (thrown) {
        if (thrown instanceof ApiError && thrown.status === PRECONDITION_FAILED) {
          setWarning({
            message: thrown.detail ?? EXISTING_PREVIEW_WARNING,
            publishTaskId,
          });
          return;
        }
        setError(thrown instanceof ApiError && thrown.detail ? thrown.detail : RETRY_FAILED);
      } finally {
        setRetrying(null);
      }
    },
    [accessToken, load, onPublicationChanged],
  );

  // The draft lives in this browser, so only this browser can prove the chosen
  // Revision is what the user is looking at. Without that proof the server has
  // nothing to compare and unsaved edits would publish unnoticed.
  useEffect(() => {
    if (selected === null) {
      setDraftHash(null);
      return;
    }
    let active = true;
    const draft = loadWorkingCopy(userId, selected.task_id);
    if (draft === null) {
      setDraftHash(selected.content_hash);
      return;
    }
    void articleContentHash(draft).then((hash) => {
      if (active) setDraftHash(hash);
    });
    return () => {
      active = false;
    };
  }, [selected, userId]);

  return (
    <section className="publication-center" aria-labelledby="publication-center-heading">
      <div className="workspace__heading">
        <h2 id="publication-center-heading">发布中心</h2>
        <button className="button button--quiet" type="button" onClick={onClose}>
          关闭
        </button>
      </div>

      {error ? <p role="alert" className="form-error">{error}</p> : null}

      <p className="section-kicker">1 · 选择草稿</p>
      {articles && articles.length === 0 ? (
        <p className="form-hint">
          还没有可发布的文章。保存某个任务当前版本的立言文章后，它会出现在这里。
        </p>
      ) : null}
      <ul className="publication-candidates publication-candidates--selectable">
        {(articles ?? []).map((article) => {
          const isSelected = selected?.revision_id === article.revision_id;
          const locked = selected !== null && !isSelected;
          return (
            <li key={article.revision_id} data-selected={isSelected || undefined}>
              <button
                className="publication-candidate-choice"
                type="button"
                aria-pressed={isSelected}
                disabled={locked}
                onClick={() => setSelected(isSelected ? null : article)}
              >
                <span className="liyan-revision__title">{article.title}</span>
                <span className="form-hint">
                  {article.task_display_name} · 草稿 {article.revision_number} · {new Date(article.saved_at).toLocaleString("zh-CN")}
                </span>
                <span className="publication-candidate-preview">{article.body_markdown.slice(0, 120)}</span>
                <span className="form-hint">{isSelected ? "已选择，再次点击可取消" : "可发布"}</span>
              </button>
              {onOpenTask ? (
                <button className="button button--quiet" type="button" onClick={() => onOpenTask(article.task_id)}>
                  打开任务
                </button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {articleCursor ? <button className="button button--quiet" type="button" onClick={() => void loadMoreArticles()}>加载更多草稿</button> : null}

      <p className="section-kicker">2 · Publishing</p>
      {selected && draftHash ? (
        <PublicationConfirmation
          userId={userId}
          accessToken={accessToken}
          article={publicationArticle(selected)}
          workingCopyHash={draftHash}
          onStatusChange={onPublicationChanged}
          onClose={() => {
            setSelected(null);
            void load();
          }}
        />
      ) : <p className="form-hint">选择一个草稿后，可配置发布目标与作者并确认锁定快照。</p>}

      <p className="section-kicker">3 · 发布历史</p>
      {records && records.length === 0 ? (
        <p className="form-hint">还没有发布记录。</p>
      ) : null}
      <ul className="publication-candidates">
        {(records ?? []).map((record) => (
          <li key={record.id}>
            <div>
              <p className="liyan-revision__title">{record.title}</p>
              <p className="form-hint">
                草稿 {record.revision_number} · {record.target.display_name} · {record.status}
              </p>
            </div>
            {record.preview_url ? (
              <a href={record.preview_url} target="_blank" rel="noreferrer">
                打开 Blog Preview
              </a>
            ) : null}
            {/* Only a definitive failure. 结果未知 gets no button here for the
                same reason it gets none on the confirmation screen: Blog may
                already hold the item, and nothing here can look. */}
            {record.status === "failed" ? (
              <button
                className="button button--quiet"
                type="button"
                disabled={retrying === record.id}
                onClick={() => void resend(record.id)}
              >
                重试本次提交
              </button>
            ) : null}
            {warning?.publishTaskId === record.id ? (
              <div className="publication-warning">
                <p role="alert" className="form-error">{warning.message}</p>
                <button
                  className="button"
                  type="button"
                  disabled={retrying === record.id}
                  onClick={() => void resend(record.id, true)}
                >
                  仍要发布
                </button>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {historyCursor ? <button className="button button--quiet" type="button" onClick={() => void loadMoreHistory()}>加载更多发布记录</button> : null}

    </section>
  );
}
