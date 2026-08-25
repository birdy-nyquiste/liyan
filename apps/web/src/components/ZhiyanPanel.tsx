import type { ZhiyanStateResponse } from "../api/client";
import { useEffect, useRef, useState } from "react";
import type { CapsuleChoice } from "./InstructionEditor";
import { useRetryCountdown } from "./useRetryCountdown";
import { ZhiyanReportView } from "./ZhiyanReportView";
import { useInterfaceLocale } from "../interfaceLocale";

const STATUS_LABELS: Record<ZhiyanStateResponse["status"], string> = {
  absent: "尚未分析",
  running: "分析进行中",
  cancelled: "分析已取消",
  failed: "分析未完成",
  succeeded: "分析已完成",
};

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
  const [expanded, setExpanded] = useState(
    () => state.status === "succeeded" || state.status === "failed",
  );
  const previousStatus = useRef(state.status);
  const manuallyChanged = useRef(false);
  useEffect(() => {
    const completed = state.status === "succeeded" || state.status === "failed";
    if (previousStatus.current !== state.status && completed && !manuallyChanged.current) {
      setExpanded(true);
    }
    previousStatus.current = state.status;
  }, [state.status]);

  return (
    <section className="zhiyan-panel" aria-labelledby={`zhiyan-${revisionId}`}>
      <button
        className="zhiyan-panel__heading zhiyan-panel__toggle"
        type="button"
        aria-expanded={expanded}
        aria-controls={`zhiyan-body-${revisionId}`}
        onClick={() => {
          manuallyChanged.current = true;
          setExpanded((current) => !current);
        }}
      >
        <div>
          <p className="section-kicker">{t("知言报告")}</p>
          <h3 id={`zhiyan-${revisionId}`}>{title}</h3>
        </div>
        <span className="source-operation__status">
          <span>{t(STATUS_LABELS[state.status])}</span>
        </span>
      </button>

      {expanded ? <div id={`zhiyan-body-${revisionId}`}>

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
            disabled={busy}
            onClick={() => onCancel(execution.id)}
          >
            {t("终止分析")}
          </button>
        ) : null}
      </div>

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
      </div> : null}
    </section>
  );
}
