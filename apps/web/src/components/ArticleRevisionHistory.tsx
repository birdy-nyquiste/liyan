import type { LiyanRevisionResponse } from "../api/client";
import { ArticleReader } from "./ArticleReader";

const savedAt = (value: string) => new Date(value).toLocaleString("zh-CN");

function RevisionContent({ revision }: { revision: LiyanRevisionResponse }) {
  return (
    <>
      <p className="liyan-revision__identity">草稿 {revision.number}</p>
      <p className="liyan-revision__title">{revision.title}</p>
      <p className="form-hint">
        {savedAt(revision.created_at)}
        {revision.restored_from_revision_id ? "（由历史草稿恢复）" : ""}
      </p>
      <ArticleReader
        label={`草稿 ${revision.number} 正文`}
        bodyMarkdown={revision.body_markdown}
      />
    </>
  );
}

export function ArticleRevisionHistory({
  history,
  publishableRevisionId,
  publicationUnavailableReason,
  disabled,
  onRestore,
}: {
  history: {
    current: LiyanRevisionResponse | null;
    historical: LiyanRevisionResponse[];
  };
  publishableRevisionId: string | null;
  publicationUnavailableReason: string | null;
  disabled: boolean;
  onRestore(revisionId: string): void;
}) {
  const { current, historical } = history;
  return (
    <section className="liyan-revisions" aria-labelledby="liyan-revisions-heading">
      <p className="section-kicker" id="liyan-revisions-heading">草稿历史</p>
      {current ? (
        <article className="liyan-revision liyan-revision--current">
          <RevisionContent revision={current} />
        </article>
      ) : (
        <p className="form-hint">尚未保存任何草稿。</p>
      )}
      {current && publishableRevisionId === current.id ? (
        <p role="status" className="form-hint">草稿 {current.number} 可用于发布。</p>
      ) : publicationUnavailableReason ? (
        <p role="status" className="form-hint">{publicationUnavailableReason}</p>
      ) : null}
      {historical.length ? (
        <ol className="liyan-revision-history">
          {historical.map((revision) => (
            <li key={revision.id} className="liyan-revision">
              <details>
                <summary>
                  草稿 {revision.number}：{revision.title}
                </summary>
                <RevisionContent revision={revision} />
              </details>
              <button
                className="button button--quiet"
                type="button"
                disabled={disabled}
                onClick={() => onRestore(revision.id)}
              >
                恢复为新草稿
              </button>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
