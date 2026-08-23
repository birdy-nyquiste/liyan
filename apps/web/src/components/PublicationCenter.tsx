import { useCallback, useEffect, useState } from "react";

import {
  listEligibleArticles,
  listPublishTasks,
  type EligibleArticleResponse,
  type PublishTaskResponse,
} from "../api/client";
import { articleContentHash } from "./articleContentHash";
import {
  PublicationConfirmation,
  type PublicationArticle,
} from "./PublicationConfirmation";
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
}: {
  userId: string;
  accessToken: string;
  onClose(): void;
  onPublicationChanged?(): void;
}) {
  const [articles, setArticles] = useState<EligibleArticleResponse[] | null>(null);
  const [records, setRecords] = useState<PublishTaskResponse[] | null>(null);
  const [selected, setSelected] = useState<EligibleArticleResponse | null>(null);
  const [draftHash, setDraftHash] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [eligible, publications] = await Promise.all([
        listEligibleArticles(accessToken),
        listPublishTasks(accessToken),
      ]);
      setArticles(eligible);
      setRecords(publications);
      setError(null);
    } catch {
      setError("发布中心加载失败，请稍后重试。");
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

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
      ) : (
        <>
          <p className="section-kicker">可发布的文章</p>
          {articles && articles.length === 0 ? (
            <p className="form-hint">
              还没有可发布的文章。保存某个任务当前版本的立言文章后，它会出现在这里。
            </p>
          ) : null}
          <ul className="publication-candidates">
            {(articles ?? []).map((article) => (
              <li key={article.revision_id}>
                <div>
                  <p className="liyan-revision__title">{article.title}</p>
                  <p className="form-hint">
                    {article.task_display_name} · Revision {article.revision_number}
                  </p>
                </div>
                <button
                  className="button button--quiet"
                  type="button"
                  onClick={() => setSelected(article)}
                >
                  发布
                </button>
              </li>
            ))}
          </ul>
        </>
      )}

      <p className="section-kicker">发布记录</p>
      {records && records.length === 0 ? (
        <p className="form-hint">还没有发布记录。</p>
      ) : null}
      <ul className="publication-candidates">
        {(records ?? []).map((record) => (
          <li key={record.id}>
            <div>
              <p className="liyan-revision__title">{record.title}</p>
              <p className="form-hint">
                Revision {record.revision_number} · {record.target.display_name} · {record.status}
              </p>
            </div>
            {record.preview_url ? (
              <a href={record.preview_url} target="_blank" rel="noreferrer">
                打开 Blog Preview
              </a>
            ) : null}
          </li>
        ))}
      </ul>

    </section>
  );
}
