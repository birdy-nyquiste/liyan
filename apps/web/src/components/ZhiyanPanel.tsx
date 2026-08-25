import type { ZhiyanStateResponse } from "../api/client";
import type { CapsuleChoice } from "./InstructionEditor";
import { useRetryCountdown } from "./useRetryCountdown";
import { ZhiyanReportView } from "./ZhiyanReportView";
import { useInterfaceLocale } from "../interfaceLocale";
import { STATUS_LABELS } from "./zhiyanStatus";

export function ZhiyanPanel({
  state,
  busy = false,
  onStart,
  onCancel,
  onRetryAllowed,
  taskVersionId,
  onCapsuleSelect,
}: {
  state: ZhiyanStateResponse;
  busy?: boolean;
  onStart(sourceRevisionId: string): void;
  onCancel(executionId: string): void;
  onRetryAllowed(): void;
  taskVersionId?: string;
  onCapsuleSelect?: (choice: CapsuleChoice) => void;
}) {
  const { locale, t, dateLocale, domainMessage } = useInterfaceLocale();
  const { source_revision_id: revisionId, source_title: title, capabilities } = state;
  const countdown = useRetryCountdown(capabilities.retry.allowed_at, onRetryAllowed);
  const execution = state.execution;
  // Cancelling a run is a request, not an act: the worker stops at its next
  // checkpoint, which can be a whole provider call away. The server records that
  // request as `cancel_requested`, and until this read it, a writer who pressed
  // 终止分析 saw a panel that still said 分析进行中 and a button that still
  // invited them to press it again.
  const stopping = execution?.status === "cancel_requested";
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
  const statusChip = (
    <span className={`source-chip source-chip--${stopping ? "processing" : state.status}`}>
      {stopping ? t("正在终止") : t(STATUS_LABELS[state.status])}
    </span>
  );

  return (
    <section className="zhiyan-panel" aria-labelledby={`zhiyan-${revisionId}`}>
      {/* The tab shows a truncated title; the report itself shows all of it. */}
      <header className="zhiyan-panel__heading">
        <h3 id={`zhiyan-${revisionId}`}>{title}</h3>
        {statusChip}
      </header>

      <div id={`zhiyan-body-${revisionId}`}>

      {unfinished && execution?.error ? (
        <p role="alert" className="form-error">
          {domainMessage(execution.error.message, execution.error.code)}
        </p>
      ) : null}

      <div className="button-row">
        {state.status === "succeeded" ? null : (
          <button
            className="button"
            type="button"
            // A disabled button is skipped by keyboard navigation, so the hint
            // explaining it has to be announced with the button rather than
            // left to be found further down the reading order.
            aria-describedby={
              !capabilities.can_start && retryHint ? `zhiyan-retry-${revisionId}` : undefined
            }
            disabled={busy || !capabilities.can_start}
            onClick={() => onStart(revisionId)}
          >
            {state.status === "absent" ? t("开始知言分析") : t("重试")}
          </button>
        )}
        {capabilities.can_cancel && execution ? (
          <button
            className="button button--quiet"
            type="button"
            aria-describedby={stopping ? `zhiyan-stopping-${revisionId}` : undefined}
            disabled={busy || stopping}
            onClick={() => onCancel(execution.id)}
          >
            {stopping ? t("正在终止…") : t("终止分析")}
          </button>
        ) : null}
      </div>

      {stopping ? (
        <p className="form-hint" role="status" id={`zhiyan-stopping-${revisionId}`}>
          {t("已请求终止，正在等待当前调用结束。")}
        </p>
      ) : null}

      {retryHint ? (
        <p className="form-hint" role="status" id={`zhiyan-retry-${revisionId}`}>
          {retryHint}
        </p>
      ) : null}

      {state.report ? (
        <>
          <p className="form-hint">
            {t("成功的知言报告不可编辑或重新生成。生成于")} {new Date(state.report.created_at).toLocaleString(dateLocale)}.
          </p>
          <ZhiyanReportView
            document={state.report.document}
            sourceTitle={title}
            idPrefix={`zhiyan-${revisionId}`}
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
