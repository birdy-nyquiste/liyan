import { useCallback, useEffect, useState } from "react";
import * as Tabs from "@radix-ui/react-tabs";

import {
  ApiError,
  cancelExecution,
  getTaskZhiyan,
  getTaskVersionZhiyan,
  refusalWithoutTiming,
  startThemeZhiyanRun,
  startZhiyanRun,
  type TaskVersionZhiyanResponse,
  type AccessToken,
} from "../api/client";
import type { CapsuleChoice } from "./InstructionEditor";
import { useFocusWhen } from "./useFocusWhen";
import { BuyCreditsLink } from "./BuyCreditsLink";
import { isCreditRefusal } from "./creditRefusal";
import { ThemePanel } from "./ThemePanel";
import { ZhiyanPanel } from "./ZhiyanPanel";
import { STATUS_LABELS } from "./zhiyanStatus";
import { useInterfaceLocale } from "../interfaceLocale";
import { EXECUTION_POLL_MS } from "./pollIntervals";

const LOAD_FAILED = "知言状态加载失败，请稍后重试。";
const START_FAILED = "知言分析未能启动，请稍后重试。";
//: The 主题 tab's own value. A fixed string rather than the snapshot id: the tab
//: a reader had open should survive the 主题 being rewritten into a new snapshot.
const THEME_TAB = "theme";
const CANCEL_FAILED = "终止知言分析失败，请稍后重试。";
const TOO_MANY_REQUESTS = 429;

export type ZhiyanAreaState = {
  versionId: string;
  done: number;
  failed: number;
  total: number;
  liyanReady: boolean;
  liyanReason: string | null;
};

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
  pollIntervalMs = EXECUTION_POLL_MS,
  onZhiyanState,
  onCapsuleSelect,
}: {
  accessToken: AccessToken;
  taskId: string;
  versionId?: string | null;
  pollIntervalMs?: number;
  onZhiyanState?(state: ZhiyanAreaState): void;
  onCapsuleSelect?(choice: CapsuleChoice): void;
}) {
  const { locale, t, domainMessage } = useInterfaceLocale();
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

  const theme = overview?.theme ?? null;
  const active =
    (overview?.sources.some((source) => source.status === "running") ?? false)
    || theme?.status === "running";
  const liyanAvailable = overview?.liyan.can_generate ?? false;
  const zhiyanHeading = useFocusWhen<HTMLHeadingElement>(
    overview !== null && !liyanAvailable,
  );

  // Report which 任务版本 the verdict belongs to. A bare boolean cannot survive
  // reads settling in any order: whoever answered last would decide.
  const loadedVersionId = overview?.task_version_id ?? null;
  // 主题 counts in the progress line, because it counts in the 立言 gate: a task
  // reading "2 / 2 份报告完成" while 立言 stayed shut was the panel disagreeing
  // with the server about what it was waiting for.
  const statuses = [
    ...(overview?.sources.map((source) => source.status) ?? []),
    ...(theme ? [theme.status] : []),
  ];
  const total = statuses.length;
  const done = statuses.filter((status) => status === "succeeded").length;
  const failed = statuses.filter((status) => status === "failed").length;
  const liyanReason = overview?.liyan.unavailable_reason;
  useEffect(() => {
    if (loadedVersionId) {
      onZhiyanState?.({
        versionId: loadedVersionId,
        done,
        failed,
        total,
        liyanReady: liyanAvailable,
        liyanReason: liyanReason ?? null,
      });
    }
  }, [loadedVersionId, done, failed, total, liyanAvailable, liyanReason, onZhiyanState]);

  // Poll only while a run is unfinished, and stop at its terminal state.
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => void load(), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [active, polls, load, pollIntervalMs]);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const sources = overview?.sources ?? [];
  const tabValues = [...(theme ? [THEME_TAB] : []), ...sources.map((s) => s.source_revision_id)];
  const selected = tabValues.find((value) => value === selectedId) ?? tabValues[0];

  const act = useCallback(
    async (action: () => Promise<unknown>, failure: string) => {
      setBusy(true);
      let refusal: string | null = null;
      try {
        await action();
      } catch (thrown) {
        // A refused retry is not a fault: the reloaded countdown already says why.
        const rateLimited = thrown instanceof ApiError && thrown.status === TOO_MANY_REQUESTS;
        refusal = refusalWithoutTiming(thrown) ?? (rateLimited ? null : failure);
      }
      // After the reload, not before it: a successful load clears the error,
      // so a refusal set first is wiped by the very reload that shows what the
      // refusal did — which is nothing, because the request was refused.
      try {
        await load();
        if (refusal) setError(refusal);
      } finally {
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

  const startTheme = useCallback(
    (themeRevisionId: string) =>
      void act(() => startThemeZhiyanRun(accessToken, themeRevisionId), START_FAILED),
    [act, accessToken],
  );

  // Remembered locally so the panel can say 正在终止 the moment it is asked,
  // rather than after the next poll answers.
  const [cancelRequestedFor, setCancelRequestedFor] = useState<string | null>(null);
  const cancel = useCallback(
    (executionId: string) => {
      setCancelRequestedFor(executionId);
      void act(() => cancelExecution(accessToken, executionId), CANCEL_FAILED);
    },
    [act, accessToken],
  );

  if (!overview) {
    return (
      <div className="task-card__zhiyan">
        {error ? (
          <p role="alert" className="form-error">{domainMessage(error)}</p>
        ) : (
          <p className="form-hint">{t("知言状态加载中")}</p>
        )}
      </div>
    );
  }

  return (
    <div className="task-card__zhiyan">
      {/* The pane is already titled 知言 and each report names its own source, so
          this line only repeated the count. It stays in the accessibility tree
          because it is the heading focus moves to when a run finishes. */}
      <h3 className="sr-only" ref={zhiyanHeading} tabIndex={-1}>
        {locale === "en" ? `${overview.sources.length} independent source reports` : `共 ${overview.sources.length} 个来源的独立报告`}
      </h3>
      {error ? (
        <p role="alert" className="form-error">
          {domainMessage(error)}
          {isCreditRefusal(error) ? <BuyCreditsLink /> : null}
        </p>
      ) : null}
      {/*
        * One report at a time. Each is six sections of prose, so stacked they
        * could not be compared anyway — reaching the second meant scrolling past
        * the whole of the first. A task holds at most three sources, which is
        * what makes a tab strip the right shape here rather than a growing list.
        * The strip stays for a single report: it names the source that report
        * came from, and the pane keeps its shape when a second source arrives.
        */}
      {overview.sources.length > 0 ? (
        <Tabs.Root
          className="zhiyan-tabs"
          value={selected}
          onValueChange={setSelectedId}
        >
          <Tabs.List className="zhiyan-tabs__list" aria-label={t("知言报告")}>
            {/* 主题 first: it is the frame the 来源 sit inside, and its report is
                the one that says what they leave out. */}
            {theme ? (
              <Tabs.Trigger
                className="zhiyan-tab zhiyan-tab--theme"
                value={THEME_TAB}
              >
                <span className="zhiyan-tab__title">{t("主题")}</span>
                <span className={`zhiyan-tab__dot zhiyan-tab__dot--${theme.status}`} aria-hidden="true" />
                <span className="sr-only">{t(STATUS_LABELS[theme.status])}</span>
              </Tabs.Trigger>
            ) : null}
            {overview.sources.map((source, position) => (
              <Tabs.Trigger
                className="zhiyan-tab"
                key={source.source_revision_id}
                value={source.source_revision_id}
              >
                <span className="zhiyan-tab__title">
                  {locale === "en" ? `Source #${position + 1}` : `来源 #${position + 1}`}
                </span>
                <span className={`zhiyan-tab__dot zhiyan-tab__dot--${source.status}`} aria-hidden="true" />
                {/* The dot is the visible signal; this is the one screen readers get. */}
                <span className="sr-only">{t(STATUS_LABELS[source.status])}</span>
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          {theme ? (
            <Tabs.Content value={THEME_TAB}>
              <ThemePanel
                state={theme}
                busy={busy}
                onStart={startTheme}
                onCancel={cancel}
                cancelRequested={cancelRequestedFor === theme.execution?.id}
                onRetryAllowed={() => void load()}
                taskVersionId={overview.task_version_id}
                onCapsuleSelect={onCapsuleSelect}
              />
            </Tabs.Content>
          ) : null}
          {overview.sources.map((source) => (
            <Tabs.Content key={source.source_revision_id} value={source.source_revision_id}>
              <ZhiyanPanel
                state={source}
                busy={busy}
                onStart={start}
                onCancel={cancel}
                cancelRequested={cancelRequestedFor === source.execution?.id}
                onRetryAllowed={() => void load()}
                taskVersionId={overview.task_version_id}
                onCapsuleSelect={onCapsuleSelect}
              />
            </Tabs.Content>
          ))}
        </Tabs.Root>
      ) : (
        overview.sources.map((source) => (
          <ZhiyanPanel
            key={source.source_revision_id}
            state={source}
            busy={busy}
            onStart={start}
            onCancel={cancel}
            onRetryAllowed={() => void load()}
            taskVersionId={overview.task_version_id}
            onCapsuleSelect={onCapsuleSelect}
          />
        ))
      )}
    </div>
  );
}
