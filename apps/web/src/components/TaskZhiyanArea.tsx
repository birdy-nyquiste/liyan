import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  cancelExecution,
  getTaskZhiyan,
  getTaskVersionZhiyan,
  startZhiyanRun,
  type TaskVersionZhiyanResponse,
} from "../api/client";
import { LiyanGate } from "./LiyanGate";
import { useFocusWhen } from "./useFocusWhen";
import { ZhiyanPanel } from "./ZhiyanPanel";

const POLL_INTERVAL_MS = 2000;

const LOAD_FAILED = "知言状态加载失败，请稍后重试。";
const START_FAILED = "知言分析未能启动，请稍后重试。";
const CANCEL_FAILED = "终止知言分析失败，请稍后重试。";
const TOO_MANY_REQUESTS = 429;

/**
 * The 知言 area of one task's current 任务版本, and the 立言 gate beside it.
 *
 * The server owns every judgement here — which runs are unfinished, what may be
 * retried and when, and whether 立言 may open. This polls only while a run is
 * unfinished, stops at the terminal state, and lets the server's capabilities
 * decide which of the two areas holds the page's focus.
 */
export function TaskZhiyanArea({
  accessToken,
  taskId,
  versionId,
  pollIntervalMs = POLL_INTERVAL_MS,
  showLiyanGate = true,
  onLiyanAvailabilityChange,
}: {
  accessToken: string;
  taskId: string;
  versionId?: string | null;
  pollIntervalMs?: number;
  showLiyanGate?: boolean;
  onLiyanAvailabilityChange?(available: boolean): void;
}) {
  const [overview, setOverview] = useState<TaskVersionZhiyanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Every completed poll advances this, so a failed poll still schedules the next.
  const [polls, setPolls] = useState(0);

  const load = useCallback(async () => {
    try {
      setOverview(
        versionId
          ? await getTaskVersionZhiyan(accessToken, taskId, versionId)
          : await getTaskZhiyan(accessToken, taskId),
      );
      setError(null);
    } catch {
      setError(LOAD_FAILED);
    } finally {
      setPolls((count) => count + 1);
    }
  }, [accessToken, taskId, versionId]);

  useEffect(() => {
    void load();
  }, [load]);

  const active = overview?.sources.some((source) => source.status === "running") ?? false;
  const open = overview?.liyan.can_generate ?? false;
  const zhiyanHeading = useFocusWhen<HTMLHeadingElement>(overview !== null && !open);

  useEffect(() => {
    onLiyanAvailabilityChange?.(open);
  }, [onLiyanAvailabilityChange, open]);

  // Poll only while a run is unfinished, and stop at its terminal state.
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => void load(), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [active, polls, load, pollIntervalMs]);

  const act = useCallback(
    async (action: () => Promise<unknown>, failure: string) => {
      setBusy(true);
      try {
        await action();
        setError(null);
      } catch (thrown) {
        // A refused retry is not a fault: the reloaded countdown already says why.
        const rateLimited = thrown instanceof ApiError && thrown.status === TOO_MANY_REQUESTS;
        setError(rateLimited ? null : failure);
      } finally {
        await load();
        setBusy(false);
      }
    },
    [load],
  );

  const start = useCallback(
    (sourceRevisionId: string) =>
      void act(() => startZhiyanRun(accessToken, sourceRevisionId), START_FAILED),
    [act, accessToken],
  );

  const cancel = useCallback(
    (executionId: string) =>
      void act(() => cancelExecution(accessToken, executionId), CANCEL_FAILED),
    [act, accessToken],
  );

  if (!overview) {
    return (
      <div className="task-card__zhiyan">
        {error ? (
          <p role="alert" className="form-error">{error}</p>
        ) : (
          <p className="form-hint">知言状态加载中</p>
        )}
      </div>
    );
  }

  return (
    <div className="task-card__zhiyan">
      <h3 className="section-kicker" ref={zhiyanHeading} tabIndex={-1}>
        知言（共 {overview.sources.length} 个来源）
      </h3>
      {error ? (
        <p role="alert" className="form-error">{error}</p>
      ) : null}
      {overview.sources.map((source) => (
        <ZhiyanPanel
          key={source.source_revision_id}
          state={source}
          busy={busy}
          onStart={start}
          onCancel={cancel}
          onRetryAllowed={() => void load()}
        />
      ))}
      {showLiyanGate ? (
        <LiyanGate liyan={overview.liyan} headingId={`liyan-${taskId}`} />
      ) : null}
    </div>
  );
}
