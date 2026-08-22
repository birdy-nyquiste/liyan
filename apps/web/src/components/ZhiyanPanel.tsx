import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelExecution,
  getZhiyanState,
  startZhiyanRun,
  type ZhiyanStateResponse,
} from "../api/client";
import { ZhiyanReportView } from "./ZhiyanReportView";

const POLL_INTERVAL_MS = 2000;

const STATUS_LABELS: Record<ZhiyanStateResponse["status"], string> = {
  absent: "尚未分析",
  running: "分析进行中",
  cancelled: "分析已取消",
  failed: "分析未完成",
  succeeded: "分析已完成",
};

export function ZhiyanPanel({
  accessToken,
  sourceRevisionId,
  sourceTitle,
  pollIntervalMs = POLL_INTERVAL_MS,
}: {
  accessToken: string;
  sourceRevisionId: string;
  sourceTitle: string;
  pollIntervalMs?: number;
}) {
  const [state, setState] = useState<ZhiyanStateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      setState(await getZhiyanState(accessToken, sourceRevisionId));
      setError(null);
    } catch {
      setError("知言状态加载失败，请稍后重试。");
    }
  }, [accessToken, sourceRevisionId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while an Execution is active, and stop at its terminal state.
  useEffect(() => {
    if (state?.status !== "running") return;
    timer.current = setTimeout(() => void load(), pollIntervalMs);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [state, load, pollIntervalMs]);

  async function start() {
    setBusy(true);
    try {
      setState(await startZhiyanRun(accessToken, sourceRevisionId));
      setError(null);
    } catch {
      setError("知言分析未能启动，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function cancel(executionId: string) {
    setBusy(true);
    try {
      await cancelExecution(accessToken, executionId);
      await load();
    } catch {
      setError("取消知言分析失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  const execution = state?.execution ?? null;
  const failure = execution?.error ?? null;

  return (
    <section className="zhiyan-panel" aria-labelledby={`zhiyan-${sourceRevisionId}`}>
      <div className="zhiyan-panel__heading">
        <div>
          <p className="section-kicker">知言报告</p>
          <h3 id={`zhiyan-${sourceRevisionId}`}>{sourceTitle}</h3>
        </div>
        <span className="source-operation__status">
          <span>{state ? STATUS_LABELS[state.status] : "加载中"}</span>
        </span>
      </div>

      {error ? (
        <p role="alert" className="form-error">
          {error}
        </p>
      ) : null}

      {(state?.status === "failed" || state?.status === "cancelled") && failure ? (
        <p role="alert" className="form-error">
          {failure.message}
        </p>
      ) : null}

      <div className="button-row">
        {state?.capabilities.can_start ? (
          <button className="button" type="button" disabled={busy} onClick={() => void start()}>
            {state.status === "absent" ? "开始知言分析" : "重新分析"}
          </button>
        ) : null}
        {state?.capabilities.can_cancel && execution ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => void cancel(execution.id)}
          >
            取消分析
          </button>
        ) : null}
      </div>

      {state?.report ? (
        <>
          <p className="form-hint">
            成功的知言报告不可编辑或重新生成。生成于{" "}
            {new Date(state.report.created_at).toLocaleString("zh-CN")}。
          </p>
          <ZhiyanReportView
            document={state.report.document}
            sourceTitle={sourceTitle}
            idPrefix={`zhiyan-${sourceRevisionId}`}
          />
        </>
      ) : null}
    </section>
  );
}
