import type { ZhiyanStateResponse } from "../api/client";
import type { CapsuleChoice } from "./InstructionEditor";
import { useRetryCountdown } from "./useRetryCountdown";
import { ZhiyanReportView } from "./ZhiyanReportView";

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
  const { source_revision_id: revisionId, source_title: title, capabilities } = state;
  const countdown = useRetryCountdown(capabilities.retry.allowed_at, onRetryAllowed);
  const execution = state.execution;
  const unfinished = state.status === "failed" || state.status === "cancelled";
  const exhausted = capabilities.retry.remaining === 0;
  const retryHint = !unfinished
    ? null
    : countdown > 0
      ? exhausted
        ? `重试次数已用完，${countdown} 秒后可再试。`
        : `${countdown} 秒后可重试，还可重试 ${capabilities.retry.remaining} 次。`
      : exhausted
        ? "重试次数已用完，请稍后再试。"
        : null;

  return (
    <section className="zhiyan-panel" aria-labelledby={`zhiyan-${revisionId}`}>
      <div className="zhiyan-panel__heading">
        <div>
          <p className="section-kicker">知言报告</p>
          <h3 id={`zhiyan-${revisionId}`}>{title}</h3>
        </div>
        <span className="source-operation__status">
          <span>{STATUS_LABELS[state.status]}</span>
        </span>
      </div>

      {unfinished && execution?.error ? (
        <p role="alert" className="form-error">
          {execution.error.message}
        </p>
      ) : null}

      <div className="button-row">
        {state.status === "succeeded" ? null : (
          <button
            className="button"
            type="button"
            disabled={busy || !capabilities.can_start}
            onClick={() => onStart(revisionId)}
          >
            {state.status === "absent" ? "开始知言分析" : "重试"}
          </button>
        )}
        {capabilities.can_cancel && execution ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => onCancel(execution.id)}
          >
            终止分析
          </button>
        ) : null}
      </div>

      {retryHint ? (
        <p className="form-hint" role="status">{retryHint}</p>
      ) : null}

      {state.report ? (
        <>
          <p className="form-hint">
            成功的知言报告不可编辑或重新生成。生成于{" "}
            {new Date(state.report.created_at).toLocaleString("zh-CN")}。
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
    </section>
  );
}
