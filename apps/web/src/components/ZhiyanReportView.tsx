import type { components } from "../api/schema";

export type ZhiyanReportDocument = components["schemas"]["ZhiyanReportDocument"];
type FactItem = components["schemas"]["FactItem"];
type FactVerdict = FactItem["verdict"];

const VERDICT_LABELS: Record<FactVerdict, string> = {
  supported: "属实",
  partially_supported: "部分属实",
  disputed: "存在争议",
  contradicted: "不属实",
  unverifiable: "暂时无法核实",
};

const VERDICT_TONES: Record<FactVerdict, string> = {
  supported: "verdict--supported",
  partially_supported: "verdict--partial",
  disputed: "verdict--disputed",
  contradicted: "verdict--contradicted",
  unverifiable: "verdict--unverifiable",
};

/** Only a plain web address may become a link; anything else stays inert text. */
function webAddress(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:" ? parsed.href : null;
  } catch {
    return null;
  }
}

function Section({
  id,
  heading,
  count,
  emptyStatement,
  children,
}: {
  id: string;
  heading: string;
  count: number;
  emptyStatement: string | null;
  children: React.ReactNode;
}) {
  return (
    <section className="zhiyan-section" aria-labelledby={id}>
      <h4 id={id}>{heading}</h4>
      {count === 0 ? (
        <p className="zhiyan-empty">{emptyStatement ?? "本部分没有内容。"}</p>
      ) : (
        children
      )}
    </section>
  );
}

export function ZhiyanReportView({
  document: report,
  sourceTitle,
  idPrefix,
}: {
  document: ZhiyanReportDocument;
  sourceTitle: string;
  /** Keeps section ids unique when a task renders several reports at once. */
  idPrefix: string;
}) {
  return (
    <article className="zhiyan-report" aria-label={`知言报告 ${sourceTitle}`}>
      <section className="zhiyan-section" aria-labelledby={`${idPrefix}-overview`}>
        <h4 id={`${idPrefix}-overview`}>总览</h4>
        <p>{report.overview}</p>
      </section>

      <section className="zhiyan-section" aria-labelledby={`${idPrefix}-source`}>
        <h4 id={`${idPrefix}-source`}>来源</h4>
        <dl className="zhiyan-facts-list">
          <dt>标题</dt>
          <dd>{report.source.title}</dd>
          <dt>出处</dt>
          <dd>{report.source.origin}</dd>
          <dt>材料类型</dt>
          <dd>{report.source.material_type}</dd>
          <dt>背景</dt>
          <dd>{report.source.context}</dd>
        </dl>
      </section>

      <Section
        id={`${idPrefix}-facts`}
        heading="事实"
        count={report.facts.items.length}
        emptyStatement={report.facts.empty_statement}
      >
        <ul className="zhiyan-items">
          {report.facts.items.map((fact) => (
            <li key={fact.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{fact.id}</span>
                <span className={`zhiyan-verdict ${VERDICT_TONES[fact.verdict]}`}>
                  {VERDICT_LABELS[fact.verdict]}
                </span>
              </p>
              <p className="zhiyan-item__claim">{fact.claim}</p>
              <p>{fact.reasoning}</p>
              {fact.evidence_refs.length > 0 ? (
                <p className="zhiyan-item__refs">
                  证据：
                  {fact.evidence_refs.map((ref) => (
                    <span key={ref} className="zhiyan-ref">
                      {ref}
                    </span>
                  ))}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id={`${idPrefix}-viewpoints`}
        heading="观点"
        count={report.viewpoints.items.length}
        emptyStatement={report.viewpoints.empty_statement}
      >
        <ul className="zhiyan-items">
          {report.viewpoints.items.map((viewpoint) => (
            <li key={viewpoint.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{viewpoint.id}</span>
                <span className="zhiyan-holder">{viewpoint.holder}</span>
              </p>
              <p className="zhiyan-item__claim">{viewpoint.statement}</p>
              <p>{viewpoint.assessment}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id={`${idPrefix}-logic`}
        heading="逻辑"
        count={report.logic.items.length}
        emptyStatement={report.logic.empty_statement}
      >
        <ul className="zhiyan-items">
          {report.logic.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
              </p>
              <p className="zhiyan-item__claim">{item.finding}</p>
              <p>{item.assessment}</p>
              <ReferenceList refs={item.refs} />
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id={`${idPrefix}-intent`}
        heading="意图"
        count={report.intent.items.length}
        emptyStatement={report.intent.empty_statement}
      >
        <ul className="zhiyan-items">
          {report.intent.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
              </p>
              <p className="zhiyan-item__claim">{item.finding}</p>
              <p>{item.reasoning}</p>
              <ReferenceList refs={item.refs} />
            </li>
          ))}
        </ul>
      </Section>

      <Section
        id={`${idPrefix}-evidence`}
        heading="证据"
        count={report.evidence.items.length}
        emptyStatement={report.evidence.empty_statement}
      >
        <ul className="zhiyan-items">
          {report.evidence.items.map((evidence) => {
            const address = webAddress(evidence.url);
            return (
              <li key={evidence.id} className="zhiyan-item">
                <p className="zhiyan-item__head">
                  <span className="zhiyan-ref">{evidence.id}</span>
                  <span className="zhiyan-holder">{evidence.publisher}</span>
                </p>
                <p className="zhiyan-item__claim">{evidence.title}</p>
                <p>{evidence.relevance}</p>
                {address ? (
                  <a href={address} target="_blank" rel="noopener noreferrer nofollow">
                    {address}
                  </a>
                ) : (
                  <p className="zhiyan-empty">该证据地址不可作为链接打开：{evidence.url}</p>
                )}
              </li>
            );
          })}
        </ul>
      </Section>
    </article>
  );
}

function ReferenceList({ refs }: { refs: string[] }) {
  if (refs.length === 0) return null;
  return (
    <p className="zhiyan-item__refs">
      依据：
      {refs.map((ref) => (
        <span key={ref} className="zhiyan-ref">
          {ref}
        </span>
      ))}
    </p>
  );
}
