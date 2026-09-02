import type { ThemeStateResponse } from "../api/client";
import type { CapsuleChoice } from "./InstructionEditor";
import { useRetryCountdown } from "./useRetryCountdown";
import { RunningNotice } from "./RunningNotice";
import { ThemeReportView } from "./ThemeReportView";
import { useInterfaceLocale } from "../interfaceLocale";
import { STATUS_LABELS } from "./zhiyanStatus";

/**
 * The 主题 half of the 知言 area: one 主题, one report, the same controls a 来源
 * gets.
 *
 * It is a sibling of `ZhiyanPanel` rather than a branch inside it. The two share
 * a shape — status, retry, cancel, report — and disagree on every word: what a
 * failure means here is that 立言 is shut with no 来源 left to fix, so the panel
 * says the one thing that reopens it.
 */
export function ThemePanel({
  state,
  busy = false,
  onStart,
  onCancel,
  cancelRequested = false,
  onRetryAllowed,
  taskVersionId,
  onCapsuleSelect,
}: {
  state: ThemeStateResponse;
  busy?: boolean;
  onStart(themeRevisionId: string): void;
  onCancel(executionId: string): void;
  cancelRequested?: boolean;
  onRetryAllowed(): void;
  taskVersionId?: string;
  onCapsuleSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t, dateLocale, domainMessage } = useInterfaceLocale();
  const { theme_revision_id: revisionId, theme, capabilities } = state;
  const countdown = useRetryCountdown(capabilities.retry.allowed_at, onRetryAllowed);
  const execution = state.execution;
  const active = state.status === "running";
  const stopping = active && (execution?.status === "cancel_requested" || cancelRequested);
  const unfinished = state.status === "failed" || state.status === "cancelled";
  const exhausted = capabilities.retry.remaining === 0;
  const retryHint = !unfinished
    ? null
    : countdown > 0
      ? exhausted
        ? locale === "en" ? `No retries remain; try again in ${countdown}s.` : `重试次数已用完，${countdown} 秒后可再试。`
        : locale === "en" ? `Retry in ${countdown}s; ${capabilities.retry.remaining} retries remain.` : `${countdown} 秒后可重试，还可重试 ${capabilities.retry.remaining} 次。`
      : exhausted
        ? t("重试次数已用完，请稍后再试。")
        : null;

  return (
    <section className="zhiyan-panel" aria-labelledby={`theme-${revisionId}`}>
      <header className="zhiyan-panel__heading">
        <h3 id={`theme-${revisionId}`}>{theme}</h3>
        <span className={`source-chip source-chip--${stopping ? "processing" : state.status}`}>
          {stopping ? t("正在终止") : t(STATUS_LABELS[state.status])}
        </span>
      </header>

      <div id={`theme-body-${revisionId}`}>
        {active && !stopping ? (
          <RunningNotice label={t("正在生成主题知言报告…")} />
        ) : null}

        {unfinished && execution?.error ? (
          <p role="alert" className="form-error">
            {domainMessage(execution.error.message, execution.error.code)}
          </p>
        ) : null}

        {unfinished && exhausted ? (
          // The only way past a report that will not succeed, said where the
          // person who is stuck is looking.
          <p className="form-hint" role="status">
            {t("若主题报告始终失败，可在编辑来源时清空主题后保存，立言即可继续。")}
          </p>
        ) : null}

        <div className="button-row zhiyan-actions">
          {state.status === "succeeded" || active ? null : (
            <button
              className="button"
              type="button"
              aria-describedby={
                !capabilities.can_start && retryHint ? `theme-retry-${revisionId}` : undefined
              }
              disabled={busy || !capabilities.can_start}
              onClick={() => onStart(revisionId)}
            >
              {state.status === "absent" ? t("开始主题知言分析") : t("重试")}
            </button>
          )}
          {capabilities.can_cancel && execution ? (
            <button
              className="button button--quiet"
              type="button"
              disabled={busy || stopping}
              onClick={() => onCancel(execution.id)}
            >
              {stopping ? t("正在终止…") : t("终止分析")}
            </button>
          ) : null}
        </div>

        {retryHint ? (
          <p className="form-hint" role="status" id={`theme-retry-${revisionId}`}>
            {retryHint}
          </p>
        ) : null}

        {state.report ? (
          <>
            <p className="form-hint">
              {t("成功的知言报告不可编辑或重新生成。生成于")}{" "}
              {new Date(state.report.created_at).toLocaleString(dateLocale)}.
            </p>
            <ThemeReportView
              document={state.report.document}
              theme={theme}
              idPrefix={`theme-${revisionId}`}
              taskVersionId={taskVersionId}
              reportId={state.report.id}
              onCapsuleSelect={onCapsuleSelect}
            />
          </>
        ) : null}
      </div>
    </section>
  );
}
