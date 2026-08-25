import type { LiyanRevisionResponse } from "../api/client";
import { ArticleReader } from "./ArticleReader";
import { useInterfaceLocale } from "../interfaceLocale";

function RevisionContent({ revision }: { revision: LiyanRevisionResponse }) {
  const { t, dateLocale } = useInterfaceLocale();
  return (
    <>
      <p className="liyan-revision__identity">{t("草稿")} {revision.number}</p>
      <p className="liyan-revision__title">{revision.title}</p>
      <p className="form-hint">
        {new Date(revision.created_at).toLocaleString(dateLocale)}
        {revision.restored_from_revision_id ? t("（由历史草稿恢复）") : ""}
      </p>
      <ArticleReader
        label={`${t("草稿")} ${revision.number} ${t("正文")}`}
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
  const { locale, t, domainMessage } = useInterfaceLocale();
  const { current, historical } = history;
  return (
    <section className="liyan-revisions" aria-labelledby="liyan-revisions-heading">
      <p className="section-kicker" id="liyan-revisions-heading">{t("草稿历史")}</p>
      {current ? (
        <article className="liyan-revision liyan-revision--current">
          <RevisionContent revision={current} />
        </article>
      ) : (
        <p className="form-hint">{t("尚未保存任何草稿。")}</p>
      )}
      {current && publishableRevisionId === current.id ? (
        <p role="status" className="form-hint">{locale === "en" ? `Draft ${current.number} is eligible for publication.` : `草稿 ${current.number} 可用于发布。`}</p>
      ) : publicationUnavailableReason ? (
        <p role="status" className="form-hint">{domainMessage(publicationUnavailableReason)}</p>
      ) : null}
      {historical.length ? (
        <ol className="liyan-revision-history">
          {historical.map((revision) => (
            <li key={revision.id} className="liyan-revision">
              <details>
                <summary>
                  {t("草稿")} {revision.number}{locale === "en" ? ": " : "："}{revision.title}
                </summary>
                <RevisionContent revision={revision} />
              </details>
              <button
                className="button button--quiet"
                type="button"
                disabled={disabled}
                onClick={() => onRestore(revision.id)}
              >
                {t("恢复为新草稿")}
              </button>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
