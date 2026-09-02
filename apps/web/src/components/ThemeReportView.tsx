import type { components } from "../api/schema";
import type { CapsuleChoice } from "./InstructionEditor";
import { useInterfaceLocale } from "../interfaceLocale";
import { CapsuleButton, EmptyState, Refs, Section } from "./reportParts";
import { webAddress } from "./webAddress";

export type ThemeReportDocument = components["schemas"]["ThemeReportDocument"];

/**
 * One 主题知言报告: what the internet holds on this subject, and what the 来源 of
 * this 任务版本 leave out.
 *
 * Six sections rather than 知言's seven, and 盲点 is the one this report exists
 * for — so it is not last. A reader who opens one section opens that one, and it
 * is the only section that talks about their own 来源.
 */
export function ThemeReportView({
  document: report,
  theme,
  idPrefix,
  taskVersionId,
  reportId,
  onCapsuleSelect,
}: {
  document: ThemeReportDocument;
  theme: string;
  idPrefix: string;
  taskVersionId?: string;
  reportId?: string;
  onCapsuleSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t } = useInterfaceLocale();
  const capsuleTitle = t("主题");
  return (
    <article className="zhiyan-report" aria-label={`${t("主题知言报告")} ${theme}`}>
      <Section id={`${idPrefix}-overview`} heading={t("概要")}>
        <dl className="zhiyan-detail-list">
          <dt>{t("主题全景")}</dt>
          <dd>{report.overview.landscape}</dd>
          <dt>{t("共识与争议")}</dt>
          <dd>{report.overview.consensus_and_dispute}</dd>
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

      <Section id={`${idPrefix}-blind-spots`} heading={t("来源之外的角度")}>
        <EmptyState
          items={report.blind_spots.items.length}
          reason={report.blind_spots.empty_state}
        />
        <ul className="zhiyan-items">
          {report.blind_spots.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
                <CapsuleButton
                  itemId={item.id}
                  reportTitle={capsuleTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  reportKind="theme"
                  onSelect={onCapsuleSelect}
                />
              </p>
              <p className="zhiyan-item__claim">{item.angle}</p>
              <p className="zhiyan-source-gap">{item.source_gap}</p>
              <p>{item.why_it_matters}</p>
              <Refs label={t("依据：")} refs={item.evidence_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-facts`} heading={t("主题事实")}>
        <EmptyState items={report.facts.items.length} reason={report.facts.empty_state} />
        <ul className="zhiyan-items">
          {report.facts.items.map((fact) => (
            <li key={fact.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{fact.id}</span>
                <CapsuleButton
                  itemId={fact.id}
                  reportTitle={capsuleTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  reportKind="theme"
                  onSelect={onCapsuleSelect}
                />
              </p>
              <p className="zhiyan-item__claim">{fact.claim}</p>
              <p>{fact.relevance}</p>
              <Refs label={t("依据：")} refs={fact.evidence_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-viewpoints`} heading={t("观点谱系")}>
        <EmptyState
          items={report.viewpoints.items.length}
          reason={report.viewpoints.empty_state}
        />
        <ul className="zhiyan-items">
          {report.viewpoints.items.map((viewpoint) => (
            <li key={viewpoint.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{viewpoint.id}</span>
                <span className="zhiyan-holder">{viewpoint.holders}</span>
                <CapsuleButton
                  itemId={viewpoint.id}
                  reportTitle={capsuleTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  reportKind="theme"
                  onSelect={onCapsuleSelect}
                />
              </p>
              <p className="zhiyan-item__claim">{viewpoint.position}</p>
              <p>{viewpoint.grounds}</p>
              <Refs label={t("依据：")} refs={viewpoint.evidence_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-disagreements`} heading={t("分歧焦点")}>
        <EmptyState
          items={report.disagreements.items.length}
          reason={report.disagreements.empty_state}
        />
        <ul className="zhiyan-items">
          {report.disagreements.items.map((item) => (
            <li key={item.id} className="zhiyan-item">
              <p className="zhiyan-item__head">
                <span className="zhiyan-ref">{item.id}</span>
                <CapsuleButton
                  itemId={item.id}
                  reportTitle={capsuleTitle}
                  taskVersionId={taskVersionId}
                  reportId={reportId}
                  reportKind="theme"
                  onSelect={onCapsuleSelect}
                />
              </p>
              <p className="zhiyan-item__claim">{item.axis}</p>
              <p>{item.sides}</p>
              <p className="zhiyan-crux">{item.crux}</p>
              <Refs label={t("依据：")} refs={item.evidence_ids} />
            </li>
          ))}
        </ul>
      </Section>

      <Section id={`${idPrefix}-evidence`} heading={t("外部依据")}>
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
                    <p className="zhiyan-empty">
                      {locale === "en"
                        ? `This evidence address cannot be opened as a link: ${evidence.url}`
                        : `该依据地址不可作为链接打开：${evidence.url}`}
                    </p>
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
