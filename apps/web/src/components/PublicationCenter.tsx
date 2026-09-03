import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  ApiError,
  listEligibleArticlePage,
  listPublishTaskPage,
  retryPublication,
  type EligibleArticleResponse,
  type PublishTaskResponse,
  type AccessToken,
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
import { useInterfaceLocale } from "../interfaceLocale";

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
/** A submission's state, in the chip vocabulary the rest of the workbench uses. */
const PUBLICATION_TONES: Record<string, string> = {
  succeeded: "succeeded",
  published: "succeeded",
  failed: "failed",
  unknown: "warning",
};

export function PublicationCenter({
  userId,
  accessToken,
  onPublicationChanged,
  onOpenTask,
  initialTaskId,
  initialRevisionId,
}: {
  userId: string;
  accessToken: AccessToken;
  onPublicationChanged?(): void;
  onOpenTask?(taskId: string): void;
  initialTaskId?: string | null;
  initialRevisionId?: string | null;
}) {
  const { t, dateLocale, domainMessage, publicationStatus, executionStatus } = useInterfaceLocale();
  const [articles, setArticles] = useState<EligibleArticleResponse[] | null>(null);
  const [records, setRecords] = useState<PublishTaskResponse[] | null>(null);
  const [articleCursor, setArticleCursor] = useState<string | null>(null);
  const [historyCursor, setHistoryCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<EligibleArticleResponse | null>(null);
  const [flowOpen, setFlowOpen] = useState(Boolean(initialTaskId && initialRevisionId));
  const [draftHash, setDraftHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // One record open at a time: each carries attempts, evidence, and a payload.
  const [openRecordId, setOpenRecordId] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<string | null>(null);
  const [warning, setWarning] = useState<{ message: string; publishTaskId: string } | null>(
    null,
  );
  const retryKeys = useRef(new Map<string, string>());
  const initialSelectionHandled = useRef(false);

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
      setError(t("发布中心加载失败，请稍后重试。"));
    }
  }, [accessToken, t]);

  const refreshPublicationHistory = useCallback(async () => {
    try {
      const publications = await listPublishTaskPage(accessToken);
      setRecords((current) => {
        if (current === null) return publications.items;
        const refreshed = new Map(publications.items.map((record) => [record.id, record]));
        const retained = current.map((record) => refreshed.get(record.id) ?? record);
        const known = new Set(retained.map((record) => record.id));
        return [...publications.items.filter((record) => !known.has(record.id)), ...retained];
      });
      setError(null);
    } catch {
      setError(t("发布任务加载失败，请稍后重试。"));
    }
  }, [accessToken, t]);

  const loadMoreArticles = useCallback(async () => {
    if (!articleCursor) return;
    const page = await listEligibleArticlePage(accessToken, articleCursor);
    setArticles((current) => [...(current ?? []), ...page.items]);
    setArticleCursor(page.next_cursor ?? null);
  }, [accessToken, articleCursor]);

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
    if (initialTaskId && initialRevisionId) setFlowOpen(true);
  }, [initialRevisionId, initialTaskId]);

  useEffect(() => {
    if (!records?.some((record) => record.status === "pending")) return;
    const timer = window.setInterval(() => void refreshPublicationHistory(), 2_000);
    return () => window.clearInterval(timer);
  }, [records, refreshPublicationHistory]);

  useEffect(() => {
    if (
      initialSelectionHandled.current
      || selected
      || !articles
      || !initialTaskId
      || !initialRevisionId
    ) return;
    const initial = articles.find(
      (article) => article.task_id === initialTaskId && article.revision_id === initialRevisionId,
    );
    if (initial) {
      initialSelectionHandled.current = true;
      setSelected(initial);
    }
    else if (articleCursor) void loadMoreArticles();
    else initialSelectionHandled.current = true;
  }, [articleCursor, articles, initialRevisionId, initialTaskId, loadMoreArticles, selected]);

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
        await refreshPublicationHistory();
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
    [accessToken, onPublicationChanged, refreshPublicationHistory],
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

  const closeFlow = () => {
    setSelected(null);
    setFlowOpen(false);
    void load();
  };

  return (
    <section className="publication-center" aria-labelledby="publication-center-heading">
      {/* The route is the publication ledger. A new submission is an explicit
          action that opens its own ordered flow above that persistent history. */}
      <header className="page-heading publication-page-heading">
        <h1 id="publication-center-heading">{t("发布")}</h1>
        {!flowOpen ? (
          <button className="button" type="button" onClick={() => setFlowOpen(true)}>
            {t("新发布")}
          </button>
        ) : null}
      </header>

      {error ? <p role="alert" className="form-error">{domainMessage(error)}</p> : null}

      {flowOpen ? (
        <section className="publication-flow" aria-labelledby="publication-flow-heading">
          <header className="publication-flow__heading">
            <h2 id="publication-flow-heading">{t("新发布")}</h2>
            <button className="button button--quiet" type="button" onClick={closeFlow}>
              {t("关闭")}
            </button>
          </header>
          <ol className="process-pipeline publication-pipeline" aria-label={t("发布")}>
        <li data-state={selected ? "complete" : "current"}>
              <span className="process-pipeline__index">1</span>
          <span>{t("选择草稿")}</span>
        </li>
        <li data-state={selected ? "current" : "locked"}>
              <span className="process-pipeline__index">2</span>
          <span>{t("确认发布")}</span>
        </li>
          </ol>

      {!selected ? (
        <section className="publication-stage" aria-labelledby="publication-drafts-heading">
          <header className="publication-stage__heading">
            <h2 id="publication-drafts-heading">{t("选择草稿")}</h2>
            <span>{articles === null ? t("读取中") : `${articles.length} ${t("草稿")}`}</span>
          </header>
          {articles === null ? <p className="publication-empty">{t("读取中")}</p> : null}
          {articles && articles.length === 0 ? (
            <p className="publication-empty">
              {t("还没有可发布的文章。保存某个任务当前版本的立言文章后，它会出现在这里。")}
            </p>
          ) : null}
          <ul className="publication-candidates publication-candidates--selectable">
            {(articles ?? []).map((article) => (
              <li key={article.revision_id}>
                <button
                  className="publication-candidate-choice"
                  type="button"
                  onClick={() => setSelected(article)}
                >
                  <span className="liyan-revision__title">{article.title}</span>
                  <span className="form-hint">
                    {article.task_display_name} · {t("草稿")} {article.revision_number} · {new Date(article.saved_at).toLocaleString(dateLocale)}
                  </span>
                  <span className="publication-candidate-preview">{article.body_markdown.slice(0, 120)}</span>
                  <span className="source-chip">{t("可发布")}</span>
                </button>
                {onOpenTask ? (
                  <button className="button button--quiet" type="button" onClick={() => onOpenTask(article.task_id)}>
                    {t("打开任务")}
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
          {articleCursor ? <button className="button button--quiet" type="button" onClick={() => void loadMoreArticles()}>{t("加载更多草稿")}</button> : null}
        </section>
      ) : (
        <section className="publication-stage publication-stage--confirmation" aria-labelledby="publication-confirmation-heading">
          <header className="publication-stage__heading">
            <h2 id="publication-confirmation-heading">{t("确认发布")}</h2>
            <span>{t("草稿")} {selected.revision_number}</span>
          </header>
          <article className="publication-selected-draft">
            <div>
              <strong className="liyan-revision__title">{selected.title}</strong>
              <p className="form-hint">
                {selected.task_display_name} · {t("草稿")} {selected.revision_number} · {new Date(selected.saved_at).toLocaleString(dateLocale)}
              </p>
            </div>
            <button className="button button--quiet" type="button" onClick={() => setSelected(null)}>
              {t("更换草稿")}
            </button>
          </article>
          {draftHash ? (
            <PublicationConfirmation
              userId={userId}
              accessToken={accessToken}
              article={publicationArticle(selected)}
              workingCopyHash={draftHash}
              onStatusChange={onPublicationChanged}
              onClose={closeFlow}
            />
          ) : <p className="publication-empty">{t("读取中")}</p>}
        </section>
          )}
        </section>
      ) : null}

      <section className="publication-history-section" aria-labelledby="publication-history-heading">
        <header className="publication-history-section__heading">
          <h2 id="publication-history-heading">{t("发布历史")}</h2>
          <span className="form-hint">
            {records === null
              ? t("读取中")
              : records.length === 0
                ? t("暂无记录")
                : t("共 {count} 条记录").replace("{count}", String(records.length))}
          </span>
        </header>
        <div className="publication-history-section__body">
        {records && records.length === 0 ? (
          <p className="creation-hint">{t("还没有发布记录。")}</p>
        ) : null}
        <ul className="publication-candidates">
        {(records ?? []).map((record) => (
          <li key={record.id}>
            <article className="publication-history-entry">
              <button
                className="publication-history-entry__summary"
                type="button"
                aria-expanded={openRecordId === record.id}
                aria-controls={`publication-record-${record.id}`}
                onClick={() => setOpenRecordId((current) => current === record.id ? null : record.id)}
              >
                {openRecordId === record.id
                  ? <ChevronDown size={15} aria-hidden="true" />
                  : <ChevronRight size={15} aria-hidden="true" />}
                <span className="publication-history-entry__name">
                  <span className="liyan-revision__title">{record.title}</span>
                  <span className="form-hint">
                    {t("草稿")} {record.revision_number} · {record.target.display_name}
                  </span>
                </span>
                <span className={`source-chip source-chip--${PUBLICATION_TONES[record.status] ?? "processing"}`}>
                  {publicationStatus(record.status)}
                </span>
              </button>
              {openRecordId === record.id ? (
              <div className="publication-history-entry__body" id={`publication-record-${record.id}`}>
              <dl className="publication-locked">
                <div><dt>{t("任务")}</dt><dd>{record.task_display_name}</dd></div>
                <div><dt>{t("作者")}</dt><dd>{record.author}</dd></div>
                <div><dt>{t("提交时间")}</dt><dd>{new Date(record.created_at).toLocaleString(dateLocale)}</dd></div>
                <div><dt>{t("完成时间")}</dt><dd>{record.completed_at ? new Date(record.completed_at).toLocaleString(dateLocale) : t("尚未完成")}</dd></div>
                <div><dt>{t("状态")}</dt><dd>{publicationStatus(record.status)}</dd></div>
                <div><dt>{t("尝试次数")}</dt><dd>{record.attempts?.length ?? 0}</dd></div>
              </dl>
              {record.failure_message ? (
                <div className="publication-evidence">
                  <h4>{t("失败原因")}</h4>
                  <p role="alert" className="form-error">
                    {domainMessage(record.failure_message, record.execution?.error?.code)}
                  </p>
                </div>
              ) : null}
              {record.attempts?.length || record.response_evidence ? (
                <details className="publication-technical-details">
                  <summary>{t("技术详情")}</summary>
                  <div className="publication-technical-details__body">
                    {record.attempts?.length ? (
                      <div className="publication-evidence">
                        <h4>{t("提交尝试")}</h4>
                        {record.attempts.map((attempt) => (
                          <dl className="publication-locked" key={attempt.id}>
                            <div><dt>{t("尝试次数")}</dt><dd>{attempt.attempt}</dd></div>
                            <div><dt>{t("状态")}</dt><dd>{executionStatus(attempt.status)}</dd></div>
                            <div><dt>{t("提交时间")}</dt><dd>{new Date(attempt.created_at).toLocaleString(dateLocale)}</dd></div>
                            <div><dt>{t("开始时间")}</dt><dd>{attempt.started_at ? new Date(attempt.started_at).toLocaleString(dateLocale) : t("尚未完成")}</dd></div>
                            <div><dt>{t("结束时间")}</dt><dd>{attempt.finished_at ? new Date(attempt.finished_at).toLocaleString(dateLocale) : t("尚未完成")}</dd></div>
                            <div><dt>{t("追踪 ID")}</dt><dd><code>{attempt.trace_id}</code></dd></div>
                            {attempt.error ? <>
                              <div><dt>{t("错误代码")}</dt><dd><code>{attempt.error.code}</code></dd></div>
                              <div><dt>{t("失败原因")}</dt><dd>{domainMessage(attempt.error.message, attempt.error.code)}</dd></div>
                            </> : null}
                          </dl>
                        ))}
                      </div>
                    ) : null}
                    {record.response_evidence ? (
                      <div className="publication-evidence">
                        <h4>{t("不可变响应证据")}</h4>
                        <pre>{JSON.stringify(record.response_evidence, null, 2)}</pre>
                      </div>
                    ) : null}
                  </div>
                </details>
              ) : null}
            {record.preview_url ? (
              <p>
                <a href={record.preview_url} target="_blank" rel="noreferrer">
                  {t("打开 Blog Preview")}
                </a>
                <span className="form-hint"> {t("Preview 不是公开发布；仍需管理员在 Blog 中发布。")}</span>
              </p>
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
                {t("重试本次提交")}
              </button>
            ) : null}
            {warning?.publishTaskId === record.id ? (
              <div className="publication-warning">
                <p role="alert" className="form-error">{domainMessage(warning.message)}</p>
                <button
                  className="button"
                  type="button"
                  disabled={retrying === record.id}
                  onClick={() => void resend(record.id, true)}
                >
                  {t("仍要发布")}
                </button>
              </div>
            ) : null}
              </div>
              ) : null}
            </article>
          </li>
        ))}
        </ul>
        {historyCursor ? <button className="button button--quiet" type="button" onClick={() => void loadMoreHistory()}>{t("加载更多发布记录")}</button> : null}
        </div>
      </section>

    </section>
  );
}
