import type { components } from "../api/schema";
import type { CapsuleChoice } from "./InstructionEditor";
import { useInterfaceLocale } from "../interfaceLocale";

export type ZhiyanReportDocument = components["schemas"]["ZhiyanReportDocument"];
type FactItem = components["schemas"]["FactItem"];
type FactVerdict = FactItem["verdict"];

/** The five 事实结论 of Agent Spec 知言 v0.4 §4.4, in report order. */
const VERDICT_TONES: Record<FactVerdict, string> = {
  有证据支持: "verdict--supported",
  部分准确: "verdict--partial",
  存在争议: "verdict--disputed",
  有证据反驳: "verdict--contradicted",
  暂无法核实: "verdict--unverifiable",
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
  children,
}: {
  id: string;
  heading: string;
  children: React.ReactNode;
}) {
  return (
    <section className="zhiyan-section" aria-labelledby={id}>
      <h4 id={id}>{heading}</h4>
      {children}
    </section>
  );
}

/** §4.1: a section with no content states why, rather than disappearing. */
function EmptyState({ items, reason }: { items: number; reason: string | null }) {
  const { t } = useInterfaceLocale();
  return items === 0 ? <p className="zhiyan-empty">{reason ?? t("本部分没有内容。")}</p> : null;
}

function Quote({ text }: { text: string }) {
  return <blockquote className="zhiyan-quote">{text}</blockquote>;
}

function Refs({ label, refs }: { label: string; refs: string[] }) {
  if (refs.length === 0) return null;
  return (
    <p className="zhiyan-item__refs">
      {label}
      {refs.map((ref) => (
        <span key={ref} className="zhiyan-ref">
          {ref}
        </span>
      ))}
    </p>
  );
}

function CapsuleButton({
  itemId,
  sourceTitle,
  taskVersionId,
  reportId,
  onSelect,
}: {
  itemId: string;
  sourceTitle: string;
  taskVersionId?: string;
  reportId?: string;
  onSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t } = useInterfaceLocale();
  if (!taskVersionId || !reportId || !onSelect) return null;
  return (
    <button
      className="zhiyan-capsule-button"
      type="button"
      aria-label={locale === "en" ? `Insert ${itemId} into the Liyan instruction` : `插入 ${itemId} 到立言指令`}
      onClick={() => onSelect({
        label: `${sourceTitle} · ${itemId}`,
        reference: {
          type: "capsule",
          task_version_id: taskVersionId,
          report_id: reportId,
          item_id: itemId,
        },
      })}
    >
      {t("加入指令")}
    </button>
  );
}

export function ZhiyanReportView({
  document: report,
  sourceTitle,
  idPrefix,
  taskVersionId,
  reportId,
  onCapsuleSelect,
}: {
  document: ZhiyanReportDocument;
  sourceTitle: string;
  /** Keeps section ids unique when a task renders several reports at once. */
  idPrefix: string;
  taskVersionId?: string;
  reportId?: string;
  onCapsuleSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t } = useInterfaceLocale();
  return (
    <article className="zhiyan-report" aria-label={`${t("知言报告")} ${sourceTitle}`}>
      <Section id={`${idPrefix}-overview`} heading={t("概要")}>
        <dl className="zhiyan-detail-list">
          <dt>{t("内容概要")}</dt>
          <dd>{report.overview.content_summary}</dd>
          <dt>{t("核查概况")}</dt>
          <dd>{report.overview.fact_check_summary}</dd>
          <dt>{t("阅读提示")}</dt>
          <dd>{report.overview.reading_note}</dd>
        </dl>
        {report.overview.key_findings.length > 0 ? (
          <ul className="zhiyan-items zhiyan-items--tight">
            {report.overview.key_findings.map((finding) => (
              <li key={finding.ref_id} className="zhiyan-item__refs">
                <span className="zhiyan-ref">{finding.ref_id}</span>
                <span>{finding.text}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </Section>

      <Section id={`${idPrefix}-source`} heading={t("“知”来源")}>
        <dl className="zhiyan-detail-list">
          <dt>{t("体裁")}</dt>
          <dd>{report.source.genre}</dd>
          <dt>{t("出处性质")}</dt>
          <dd>{report.source.provenance}</dd>
          <dt>{t("完整性")}</dt>
          <dd>{report.source.completeness}</dd>
          <dt>{t("来源说明")}</dt>
          <dd>{report.source.note}</dd>
        </dl>
      </Section>

      <Section id={`${idPrefix}-facts`} heading={t("“知”事实")}>
        <EmptyState items={report.facts.items.length} reason={report.facts.empty_state} />
        <ul className="zhiyan-items">
          {report.facts.items.map((fact) => (
            <li key={fact.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{fact.id}</span>
                <span className={`zhiyan-verdict ${VERDICT_TONES[fact.verdict]}`}>
                  {fact.verdict}
                </span>
                <CapsuleButton
                  itemId={fact.id}
                  sourceTitle={sourceTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  onSelect={onCapsuleSelect}
                />
              </p>
              <Quote text={fact.quote} />
              <p className="zhiyan-item__claim">{fact.claim}</p>
              <p>{fact.explanation}</p>
              <Refs label={t("依据：")} refs={fact.evidence_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-viewpoints`} heading={t("“知”观点")}>
        <EmptyState
          items={report.viewpoints.items.length}
          reason={report.viewpoints.empty_state}
        />
        <ul className="zhiyan-items">
          {report.viewpoints.items.map((viewpoint) => (
            <li key={viewpoint.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{viewpoint.id}</span>
                <span className="zhiyan-holder">{viewpoint.owner}</span>
                <CapsuleButton
                  itemId={viewpoint.id}
                  sourceTitle={sourceTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  onSelect={onCapsuleSelect}
                />
              </p>
              <Quote text={viewpoint.quote} />
              <p className="zhiyan-item__claim">{viewpoint.viewpoint}</p>
              <p>{viewpoint.analysis}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-logic`} heading={t("“知”逻辑")}>
        <p className="zhiyan-argument-chain">{report.logic.argument_chain}</p>
        <EmptyState items={report.logic.items.length} reason={report.logic.empty_state} />
        <ul className="zhiyan-items">
          {report.logic.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
                <CapsuleButton
                  itemId={item.id}
                  sourceTitle={sourceTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  onSelect={onCapsuleSelect}
                />
              </p>
              <Quote text={item.quote} />
              <p className="zhiyan-item__claim">{item.judgment}</p>
              <p>{item.explanation}</p>
              <Refs label={t("关联：")} refs={item.related_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-intent`} heading={t("“知”意图")}>
        <dl className="zhiyan-detail-list">
          <dt>{t("明确目的")}</dt>
          <dd>{report.intent.explicit_purpose}</dd>
          <dt>{t("目标受众")}</dt>
          <dd>{report.intent.target_audience}</dd>
        </dl>
        {report.intent.expression_methods.length > 0 ? (
          <ul className="zhiyan-items zhiyan-items--tight">
            {report.intent.expression_methods.map((method) => (
              <li key={method}>{method}</li>
            ))}
          </ul>
        ) : null}
        <EmptyState items={report.intent.items.length} reason={report.intent.empty_state} />
        <ul className="zhiyan-items">
          {report.intent.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
                <CapsuleButton
                  itemId={item.id}
                  sourceTitle={sourceTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  onSelect={onCapsuleSelect}
                />
              </p>
              <Quote text={item.quote} />
              <p className="zhiyan-item__claim">{item.possible_intent}</p>
              <p>{item.explanation}</p>
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-evidence`} heading={t("“知”依据")}>
        <EmptyState items={report.evidence.items.length} reason={report.evidence.empty_state} />
        <ul className="zhiyan-items">
          {report.evidence.items.map((evidence) => {
            const address = webAddress(evidence.url);
            return (
              <li key={evidence.id} className="zhiyan-item">
                <p className="zhiyan-item__head">
                  <span className="zhiyan-ref">{evidence.id}</span>
                </p>
                {address ? (
                  <p className="zhiyan-item__claim">
                    <a href={address} target="_blank" rel="noopener noreferrer nofollow">
                      {evidence.title}
                    </a>
                  </p>
                ) : (
                  <>
                    <p className="zhiyan-item__claim">{evidence.title}</p>
                    <p className="zhiyan-empty">{locale === "en" ? `This evidence address cannot be opened as a link: ${evidence.url}` : `该依据地址不可作为链接打开：${evidence.url}`}</p>
                  </>
                )}
                <p>{evidence.explanation}</p>
              </li>
            );
          })}
        </ul>
      </Section>
    </article>
  );
}
