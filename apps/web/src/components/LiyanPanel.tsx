import { useCallback, useEffect, useRef, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";

import {
  ApiError,
  cancelExecution,
  getTaskLiyan,
  refusalWithoutTiming,
  restoreLiyanRevision,
  saveLiyanRevision,
  startLiyanRun,
  type InstructionDocument,
  type LiyanStateResponse,
  type StartLiyanRunRequest,
} from "../api/client";
import { useFocusWhen } from "./useFocusWhen";
import { useRetryCountdown } from "./useRetryCountdown";
import { ArticleRevisionHistory } from "./ArticleRevisionHistory";
import {
  PublicationConfirmation,
  type PublicationArticle,
} from "./PublicationConfirmation";
import { ArticleWorkingCopyEditor } from "./ArticleWorkingCopyEditor";
import { ConfirmDialog } from "./ConfirmDialog";
import { articleContentHash, draftMatchesRevision } from "./articleContentHash";
import { InstructionEditor, type CapsuleSelection } from "./InstructionEditor";
import { canonicalizeArticleMarkdown } from "./articleMarkdown";
import { useInterfaceLocale } from "../interfaceLocale";
import {
  loadWorkingCopy,
  saveWorkingCopy,
  type LiyanWorkingCopy,
} from "./workingCopyStorage";
import { EXECUTION_POLL_MS } from "./pollIntervals";

const TOO_MANY_REQUESTS = 429;
const CONFLICT = 409;
const STALE_BASE = "文章已有更新的 Revision，请先查看最新内容。";
const UNSAVED_EDITS = "有未保存的修改，请先保存后再发布。";
const DISCARD_ON_RESTORE = "恢复历史 Revision 会覆盖当前未保存的修改，确定继续吗？";
const EMPTY_INSTRUCTION: InstructionDocument = { content: [] };

const hasInstructionContent = (value: InstructionDocument) =>
  (value.content ?? []).some((part) =>
    part.type === "capsule" || (part.type === "text" && part.text.trim().length > 0),
  );

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
  taskLabel = "",
  capsuleSelection = null,
  pollIntervalMs = EXECUTION_POLL_MS,
  onPublicationChanged,
  onPublish,
}: {
  userId: string;
  accessToken: string;
  taskId: string;
  taskLabel?: string;
  capsuleSelection?: CapsuleSelection | null;
  pollIntervalMs?: number;
  onPublicationChanged?(): void;
  onPublish?(taskId: string, revisionId: string): void;
}) {
  const { locale, t, domainMessage } = useInterfaceLocale();
  const [state, setState] = useState<LiyanStateResponse | null>(null);
  const [instruction, setInstruction] = useState<InstructionDocument>({ content: [] });
  const [workingCopy, setWorkingCopy] = useState<LiyanWorkingCopy | null>(() =>
    loadWorkingCopy(userId, taskId));
  const [lastRequest, setLastRequest] = useState<StartLiyanRunRequest | null>(null);
  const [startedExecutionId, setStartedExecutionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [polls, setPolls] = useState(0);
  const [workingCopyHash, setWorkingCopyHash] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const historyTriggerRef = useRef<HTMLButtonElement>(null);
  const loadedOnce = useRef(false);
  const startedExecutionIdRef = useRef<string | null>(null);
  const appliedResultIdRef = useRef<string | null>(null);
  const workingCopyHashRef = useRef<string | null>(null);
  const unsavedEditsRef = useRef(false);
  // Overwriting unsaved edits asks first — in the page, because a native
  // confirm() the browser suppresses returns false and silently cancels.
  const [restoringRevisionId, setRestoringRevisionId] = useState<string | null>(null);

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
      appliedResultIdRef.current = next.result.id;
    }
  }, [updateWorkingCopy]);

  const load = useCallback(async () => {
    try {
      // The draft's hash travels with every read, so the server decides whether the
      // newest Revision is still publishable rather than being asked to guess.
      const next = await getTaskLiyan(accessToken, taskId, workingCopyHashRef.current);
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

  useEffect(() => {
    let current = true;
    if (workingCopy === null) {
      workingCopyHashRef.current = null;
      setWorkingCopyHash(null);
      return;
    }
    void articleContentHash(workingCopy).then((hash) => {
      if (!current) return;
      workingCopyHashRef.current = hash;
      setWorkingCopyHash(hash);
    });
    return () => {
      current = false;
    };
  }, [workingCopy]);

  const active = state?.status === "running";
  useEffect(() => {
    if (!active) return;
    const timer = setTimeout(() => void load(), pollIntervalMs);
    return () => clearTimeout(timer);
  }, [active, load, pollIntervalMs, polls]);

  async function generate(useDefault = false) {
    setBusy(true);
    const submittedInstruction = useDefault ? EMPTY_INSTRUCTION : instruction;
    const request = state?.status === "failed" && lastRequest
        ? { ...lastRequest, idempotency_key: crypto.randomUUID() }
        : state?.status === "absent" && lastRequest
          ? lastRequest
        : {
            idempotency_key: crypto.randomUUID(),
            instruction: submittedInstruction,
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
      setInstruction((current) =>
        JSON.stringify(current) === JSON.stringify(submittedInstruction)
          ? EMPTY_INSTRUCTION
          : current,
      );
      setError(null);
    } catch (thrown) {
      const refusal =
        refusalWithoutTiming(thrown) ??
        (thrown instanceof ApiError && thrown.status === TOO_MANY_REQUESTS
          ? null
          : "立言生成未能启动，请稍后重试。");
      // The reload has to come first: it clears the error on success, so a
      // refusal set before it would be wiped by the read that follows it.
      await load();
      if (refusal) setError(refusal);
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

  async function save() {
    if (!workingCopy) return;
    setBusy(true);
    try {
      const next = await saveLiyanRevision(accessToken, taskId, {
        idempotency_key: crypto.randomUUID(),
        base_revision_id: state?.revisions.current?.id ?? null,
        title: workingCopy.title.trim(),
        body_markdown: workingCopy.body_markdown.trim(),
      });
      setState(next);
      setError(null);
    } catch (thrown) {
      // A rejected save must never discard the browser-local draft.
      const stale = thrown instanceof ApiError && thrown.status === CONFLICT;
      // The draft stays untouched; only the Revision it must be based on is refreshed,
      // so the rejection leaves the newer Revision on screen to compare against.
      if (stale) await load();
      setError(stale ? STALE_BASE : "保存文章失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  async function restore(revisionId: string) {
    setBusy(true);
    try {
      const next = await restoreLiyanRevision(
        accessToken,
        taskId,
        revisionId,
        crypto.randomUUID(),
      );
      setState(next);
      if (next.revisions.current) {
        updateWorkingCopy({
          title: next.revisions.current.title,
          body_markdown: canonicalizeArticleMarkdown(next.revisions.current.body_markdown),
        });
      }
      setError(null);
    } catch {
      setError("恢复历史 Revision 失败，请稍后重试。");
    } finally {
      setBusy(false);
    }
  }

  function recover() {
    if (!state?.result) return;
    updateWorkingCopy(workingCopyFromResult(state.result));
    appliedResultIdRef.current = state.result.id;
  }

  const recoveredResult =
    loadedOnce.current && state?.result && workingCopy === null && startedExecutionId === null;
  const unsavedEdits = !draftMatchesRevision(
    workingCopy,
    workingCopyHash,
    state?.revisions.current?.content_hash ?? null,
  );
  /**
   * Why 保存 Revision cannot be pressed, in the user's terms.
   *
   * Three different states disable one button, and "nothing changed" is by far
   * the most common — a user who has just saved and presses it again deserves
   * to be told that rather than left with a dead control.
   */
  const saveBlockedReason = !workingCopy
    ? null
    : !state?.capabilities.can_save
      ? (state?.capabilities.unavailable_reason ?? "当前无法保存 Revision。")
      : !unsavedEdits
        ? "没有未保存的修改。"
        : null;
  // One expression decides both, so the button and its explanation cannot
  // drift into disagreeing about why it is dead.
  const saveDisabled = busy || saveBlockedReason !== null;
  const composerHasContent = hasInstructionContent(instruction);
  const publishableRevisionId = unsavedEdits
    ? null
    : state?.capabilities.publishable_revision_id ?? null;
  const publishableRevision =
    publishableRevisionId && state?.revisions.current?.id === publishableRevisionId
      ? state.revisions.current
      : null;
  const publicationArticle: PublicationArticle | null = publishableRevision
    ? {
        taskId,
        taskLabel: taskLabel || "本立言任务",
        revisionId: publishableRevision.id,
        revisionNumber: publishableRevision.number,
        title: publishableRevision.title,
        bodyMarkdown: publishableRevision.body_markdown,
      }
    : null;
  const failureMessage = state?.execution?.error?.message;
  const retry = state?.capabilities.retry;
  const reloadWhenAllowed = useCallback(() => void load(), [load]);
  const countdown = useRetryCountdown(retry?.allowed_at ?? null, reloadWhenAllowed);
  const heading = useFocusWhen<HTMLHeadingElement>(state?.capabilities.can_generate ?? false);
  useEffect(() => {
    unsavedEditsRef.current = unsavedEdits;
  }, [unsavedEdits]);

  return (
    <section className="zhiyan-panel liyan-panel" aria-labelledby={`liyan-${taskId}`}>
      <h3 id={`liyan-${taskId}`} ref={heading} tabIndex={-1}>{t("立言文章")}</h3>

      <p className="liyan-instruction-label">{t("立言指令（可选）")}</p>
      <InstructionEditor
        taskId={taskId}
        value={instruction}
        disabled={busy}
        selection={capsuleSelection}
        onChange={setInstruction}
      />

      {error ? <p role="alert" className="form-error">{domainMessage(error)}</p> : null}
      {state?.status === "failed" && failureMessage ? (
        <p role="alert" className="form-error">{domainMessage(failureMessage, state.execution?.error?.code)}</p>
      ) : null}
      {state?.status === "cancelled" && failureMessage ? (
        <p role="status" className="form-hint">{domainMessage(failureMessage, state.execution?.error?.code)}</p>
      ) : null}
      {state?.capabilities.unavailable_reason ? (
        <p role="status" className="form-hint" id={`liyan-blocked-${taskId}`}>
          {domainMessage(state.capabilities.unavailable_reason)}
        </p>
      ) : null}

      <div className="button-row">
        <button
          className="button button--quiet"
          type="button"
          // The reason 立言 is closed is already on screen; a disabled button is
          // skipped by keyboard navigation, so it is named here as well rather
          // than left somewhere in the reading order to be found.
          aria-describedby={
            !state?.capabilities.can_generate && state?.capabilities.unavailable_reason
              ? `liyan-blocked-${taskId}`
              : undefined
          }
          disabled={busy || active || composerHasContent || !state?.capabilities.can_generate}
          onClick={() => void generate(true)}
        >
          {t("默认生成")}
        </button>
        <button
          className="button"
          type="button"
          disabled={busy || (!active && state?.status !== "failed" && (!composerHasContent || !state?.capabilities.can_generate))}
          onClick={() => void (active ? cancel() : generate())}
        >
          {active ? t("停止") : state?.status === "failed" ? t("重试") : t("发送")}
        </button>
        {workingCopy ? (
          <button
            className="button button--quiet"
            type="button"
            aria-describedby={saveBlockedReason ? `liyan-save-blocked-${taskId}` : undefined}
            disabled={saveDisabled}
            onClick={() => void save()}
          >
            {t("保存草稿")}
          </button>
        ) : null}
        {state ? (
          <button ref={historyTriggerRef} className="button button--quiet" type="button" onClick={() => setHistoryOpen(true)}>
            {t("草稿历史")}
          </button>
        ) : null}
        {publicationArticle && !publishing ? (
          <button
            className="button button--quiet"
            type="button"
            disabled={busy}
            onClick={() => {
              if (onPublish) onPublish(publicationArticle.taskId, publicationArticle.revisionId);
              else setPublishing(true);
            }}
          >
            {t("发布")}
          </button>
        ) : null}
      </div>

      {saveBlockedReason ? (
        <p className="form-hint" id={`liyan-save-blocked-${taskId}`}>{domainMessage(saveBlockedReason)}</p>
      ) : null}

      {retry && retry.remaining === 0 ? (
        <p className="form-hint">{t("重试次数已用完，请稍后再试。")}</p>
      ) : countdown > 0 && retry ? (
        <p className="form-hint">
          {locale === "en" ? `Retry in ${countdown}s; ${retry.remaining} retries remain.` : `${countdown} 秒后可重试，还可重试 ${retry.remaining} 次。`}
        </p>
      ) : null}

      {recoveredResult ? (
        <div className="liyan-result-offer">
          <p>{t("有一份已完成的立言结果可载入。")}</p>
          <button className="button button--quiet" type="button" onClick={recover}>
            {t("载入为未保存草稿")}
          </button>
        </div>
      ) : null}

      {publishing && publicationArticle ? (
        <PublicationConfirmation
          userId={userId}
          accessToken={accessToken}
          article={publicationArticle}
          // The server re-checks the draft against the Revision it is asked to
          // publish, so an edit made in another tab cannot slip through.
          workingCopyHash={workingCopyHash}
          onStatusChange={onPublicationChanged}
          onClose={() => setPublishing(false)}
        />
      ) : null}

      {state ? (
        <Dialog.Root open={historyOpen} onOpenChange={setHistoryOpen}>
          <Dialog.Portal>
            <Dialog.Overlay className="dialog-overlay" />
            <Dialog.Content
              className="draft-history-sheet"
              onCloseAutoFocus={(event) => {
                event.preventDefault();
                historyTriggerRef.current?.focus();
              }}
            >
              <div className="workspace__heading">
                <Dialog.Title>{t("草稿历史")}</Dialog.Title>
                <Dialog.Close className="button button--quiet">{t("关闭")}</Dialog.Close>
              </div>
              <ArticleRevisionHistory
                history={state.revisions}
                publishableRevisionId={publishableRevisionId}
                publicationUnavailableReason={
                  unsavedEdits ? UNSAVED_EDITS : state.capabilities.publication_unavailable_reason
                }
                disabled={busy || !state.capabilities.can_save}
                onRestore={(revisionId) => {
                  if (unsavedEditsRef.current) setRestoringRevisionId(revisionId);
                  else void restore(revisionId);
                }}
              />
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      ) : null}

      {workingCopy ? (
        <ArticleWorkingCopyEditor
          taskId={taskId}
          value={workingCopy}
          disabled={active || busy}
          onChange={updateWorkingCopy}
        />
      ) : null}

      <ConfirmDialog
        open={restoringRevisionId !== null}
        title={t("恢复这个历史 Revision？")}
        body={t(DISCARD_ON_RESTORE)}
        confirmLabel={t("恢复")}
        danger
        onOpenChange={(open) => { if (!open) setRestoringRevisionId(null); }}
        onConfirm={() => {
          const revisionId = restoringRevisionId;
          setRestoringRevisionId(null);
          if (revisionId) void restore(revisionId);
        }}
      />
    </section>
  );
}
