import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  cancelExecution,
  getTaskLiyan,
  startLiyanRun,
  type LiyanStateResponse,
  type StartLiyanRunRequest,
} from "../api/client";
import { useFocusWhen } from "./useFocusWhen";
import { useRetryCountdown } from "./useRetryCountdown";
import { ArticleWorkingCopyEditor } from "./ArticleWorkingCopyEditor";
import { canonicalizeArticleMarkdown } from "./articleMarkdown";
import {
  loadWorkingCopy,
  saveWorkingCopy,
  type LiyanWorkingCopy,
} from "./workingCopyStorage";

const DEFAULT_POLL_INTERVAL_MS = 2000;
const TOO_MANY_REQUESTS = 429;

const workingCopyFromResult = (
  result: NonNullable<LiyanStateResponse["result"]>,
): LiyanWorkingCopy => ({
  title: result.title,
  body_markdown: canonicalizeArticleMarkdown(result.body_markdown),
});

export function LiyanPanel({
  userId,
  accessToken,
  taskId,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: {
  userId: string;
  accessToken: string;
  taskId: string;
  pollIntervalMs?: number;
}) {
  const [state, setState] = useState<LiyanStateResponse | null>(null);
  const [instruction, setInstruction] = useState("");
  const [workingCopy, setWorkingCopy] = useState<LiyanWorkingCopy | null>(() =>
    loadWorkingCopy(userId, taskId));
  const [lastRequest, setLastRequest] = useState<StartLiyanRunRequest | null>(null);
  const [startedExecutionId, setStartedExecutionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [polls, setPolls] = useState(0);
  const loadedOnce = useRef(false);
  const startedExecutionIdRef = useRef<string | null>(null);
  const appliedResultIdRef = useRef<string | null>(null);

  const updateWorkingCopy = useCallback((next: LiyanWorkingCopy) => {
    setWorkingCopy(next);
    saveWorkingCopy(userId, taskId, next);
  }, [taskId, userId]);

  const applyStartedResult = useCallback((next: LiyanStateResponse) => {
    if (
      next.result &&
      next.result.execution_id === startedExecutionIdRef.current &&
      next.result.id !== appliedResultIdRef.current
    ) {
      updateWorkingCopy(workingCopyFromResult(next.result));
      setInstruction(next.result.instruction);
      appliedResultIdRef.current = next.result.id;
    }
  }, [updateWorkingCopy]);

  const load = useCallback(async () => {
    try {
      const next = await getTaskLiyan(accessToken, taskId);
      setState(next);
      applyStartedResult(next);
      if (next.request) {
        setLastRequest((current) => current ?? {
          idempotency_key: crypto.randomUUID(),
          instruction: next.request!.instruction,
          working_copy: next.request!.working_copy,
        });
      }
      setError(null);
      loadedOnce.current = true;
    } catch {
      setError("立言状态加载失败，请稍后重试。");
    } finally {
      setPolls((count) => count + 1);
    }
  }, [accessToken, applyStartedResult, taskId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = state?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => void load(), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [active, load, pollIntervalMs, polls]);

  async function generate() {
    setBusy(true);
    const request = state?.status === "failed" && lastRequest
        ? { ...lastRequest, idempotency_key: crypto.randomUUID() }
        : state?.status === "absent" && lastRequest
          ? lastRequest
        : {
            idempotency_key: crypto.randomUUID(),
            instruction,
            working_copy: workingCopy,
          };
    setLastRequest(request);
    try {
      const next = await startLiyanRun(accessToken, taskId, request);
      const executionId = next.execution?.id ?? null;
      startedExecutionIdRef.current = executionId;
      setStartedExecutionId(executionId);
      setState(next);
      applyStartedResult(next);
      setError(null);
    } catch (thrown) {
      setError(
        thrown instanceof ApiError && thrown.status === TOO_MANY_REQUESTS
          ? null
          : "立言生成未能启动，请稍后重试。",
      );
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    if (!state?.execution) return;
    setBusy(true);
    try {
      await cancelExecution(accessToken, state.execution.id);
      setError(null);
    } catch {
      setError("终止立言生成失败，请稍后重试。");
    } finally {
      await load();
      setBusy(false);
    }
  }

  function recover() {
    if (!state?.result) return;
    updateWorkingCopy(workingCopyFromResult(state.result));
    setInstruction(state.result.instruction);
    appliedResultIdRef.current = state.result.id;
  }

  const recoveredResult =
    loadedOnce.current && state?.result && workingCopy === null && startedExecutionId === null;
  const failureMessage = state?.execution?.error?.message;
  const retry = state?.capabilities.retry;
  const reloadWhenAllowed = useCallback(() => void load(), [load]);
  const countdown = useRetryCountdown(retry?.allowed_at ?? null, reloadWhenAllowed);
  const heading = useFocusWhen<HTMLHeadingElement>(state?.capabilities.can_generate ?? false);

  return (
    <section className="zhiyan-panel liyan-panel" aria-labelledby={`liyan-${taskId}`}>
      <p className="section-kicker">立言</p>
      <h3 id={`liyan-${taskId}`} ref={heading} tabIndex={-1}>立言文章</h3>

      <label htmlFor={`liyan-instruction-${taskId}`}>立言指令（可选）</label>
      <textarea
        id={`liyan-instruction-${taskId}`}
        value={instruction}
        disabled={active || busy}
        onChange={(event) => setInstruction(event.target.value)}
        placeholder="留空时使用立言 Prompt 内置的默认方式"
      />

      {error ? <p role="alert" className="form-error">{error}</p> : null}
      {state?.status === "failed" && failureMessage ? (
        <p role="alert" className="form-error">{failureMessage}</p>
      ) : null}
      {state?.status === "cancelled" && failureMessage ? (
        <p role="status" className="form-hint">{failureMessage}</p>
      ) : null}
      {state?.capabilities.unavailable_reason ? (
        <p role="status" className="form-hint">{state.capabilities.unavailable_reason}</p>
      ) : null}

      <div className="button-row">
        <button
          className="button"
          type="button"
          disabled={busy || !state?.capabilities.can_generate}
          onClick={() => void generate()}
        >
          {state?.status === "failed" ? "重试" : "生成立言"}
        </button>
        {state?.capabilities.can_cancel && state.execution ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => void cancel()}
          >
            终止生成
          </button>
        ) : null}
      </div>

      {retry && retry.remaining === 0 ? (
        <p className="form-hint">重试次数已用完，请稍后再试。</p>
      ) : countdown > 0 && retry ? (
        <p className="form-hint">
          {countdown} 秒后可重试，还可重试 {retry.remaining} 次。
        </p>
      ) : null}

      {recoveredResult ? (
        <div className="liyan-result-offer">
          <p>有一份已完成的立言结果可载入。</p>
          <button className="button button--quiet" type="button" onClick={recover}>
            载入为未保存草稿
          </button>
        </div>
      ) : null}

      {workingCopy ? (
        <ArticleWorkingCopyEditor
          taskId={taskId}
          value={workingCopy}
          disabled={active || busy}
          onChange={updateWorkingCopy}
        />
      ) : null}
    </section>
  );
}
