import { type KeyboardEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, deleteTask, renameTask, type AccessToken } from "../api/client";
import type { TaskSummary } from "../auth/state";
import { useInterfaceLocale } from "../interfaceLocale";
import { ConfirmDialog } from "./ConfirmDialog";
import { TaskZhiyanArea, type ZhiyanAreaState } from "./TaskZhiyanArea";
import { LiyanPanel } from "./LiyanPanel";
import type { CapsuleChoice, CapsuleSelection } from "./InstructionEditor";
import { TaskSourceVersions } from "./TaskSourceVersions";

type TaskWorkspace = "context" | "work";

export function TaskCard({
  task: initialTask,
  userId,
  accessToken,
  opened = false,
  onOpen,
  onSourceEditingChange,
  onDelete,
  onPublicationChanged,
  onPublish,
}: {
  task: TaskSummary;
  userId: string;
  accessToken: AccessToken;
  opened?: boolean;
  onOpen?(taskId: string): void;
  onSourceEditingChange?(taskId: string, editing: boolean): void;
  onDelete?(taskId: string): void;
  onPublicationChanged?(): void;
  onPublish?(taskId: string, revisionId: string): void;
}) {
  const { locale, t, dateLocale, domainMessage } = useInterfaceLocale();
  const [task, setTask] = useState(initialTask);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState(task.current_version_id);
  const [zhiyan, setZhiyan] = useState<ZhiyanAreaState | null>(null);
  const [workspace, setWorkspace] = useState<TaskWorkspace>(() => {
    const stored = window.localStorage.getItem(`liyan.taskWorkspace.${initialTask.id}`);
    if (stored === "context" || stored === "work") return stored;

    // Preserve the writer's last view when upgrading from the former four-tab
    // navigation. 来源 and 主题 were one surface; 知言 and 立言 were the other.
    const legacyStage = window.localStorage.getItem(`liyan.taskStage.${initialTask.id}`);
    return legacyStage === "work" || legacyStage === "zhiyan" || legacyStage === "liyan"
      ? "work"
      : "context";
  });
  const [capsuleSelection, setCapsuleSelection] = useState<CapsuleSelection | null>(null);
  const cardRef = useRef<HTMLElement>(null);
  const cancelRenameRef = useRef(false);

  useEffect(() => {
    if (opened) cardRef.current?.focus();
  }, [opened]);

  useEffect(() => {
    setTask((current) => ({
      ...current,
      can_delete: initialTask.can_delete,
      delete_disabled_reason: initialTask.delete_disabled_reason,
    }));
  }, [initialTask.can_delete, initialTask.delete_disabled_reason]);

  async function saveName() {
    if (cancelRenameRef.current) {
      cancelRenameRef.current = false;
      return;
    }
    const normalized = name.trim().replace(/\s+/g, " ");
    if (!normalized || normalized === task.display_name) {
      setName(task.display_name);
      setEditing(false);
      return;
    }
    try {
      setTask(await renameTask(accessToken, task.id, normalized));
      setName(normalized);
      setEditing(false);
      setError(null);
    } catch {
      setError(t("重命名失败，请重试。"));
    }
  }

  function renameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      event.currentTarget.blur();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      cancelRenameRef.current = true;
      setName(task.display_name);
      setEditing(false);
    }
  }

  async function removeTask() {
    setDeleting(true);
    try {
      await deleteTask(accessToken, task.id);
      onDelete?.(task.id);
    } catch (thrown) {
      setError(
        thrown instanceof ApiError && thrown.detail
          ? domainMessage(thrown.detail)
          : t("删除失败，请稍后重试。"),
      );
      setDeleting(false);
    }
  }

  // 立言 is open only for the version the server actually cleared, so a later
  // version-list read can no longer close an area that is genuinely ready.
  const liyanReady = zhiyan !== null && zhiyan.liyanReady && zhiyan.versionId === selectedVersionId;
  const noteZhiyanState = useCallback((state: ZhiyanAreaState) => setZhiyan(state), []);
  const viewingCurrent = selectedVersionId === task.current_version_id;
  const sourceCount = task.additional_source_count + 1;

  const zhiyanSummary = zhiyan === null
    ? t("读取中")
    : zhiyan.failed > 0
      ? locale === "en" ? `${zhiyan.failed} source analyses failed` : `${zhiyan.failed} 个来源分析失败`
      : zhiyan.done === zhiyan.total
        ? locale === "en" ? `${zhiyan.total} reports complete` : `${zhiyan.total} 份报告已完成`
        : locale === "en" ? `${zhiyan.done} / ${zhiyan.total} reports complete` : `${zhiyan.done} / ${zhiyan.total} 份报告完成`;

  const selectCapsule = (choice: CapsuleChoice) => {
    setCapsuleSelection((current) => ({ ...choice, nonce: (current?.nonce ?? 0) + 1 }));
  };

  const chooseWorkspace = (next: TaskWorkspace) => {
    setWorkspace(next);
    window.localStorage.setItem(`liyan.taskWorkspace.${task.id}`, next);
    window.requestAnimationFrame(() => {
      // On mobile, reveal the beginning of the newly selected workspace below
      // the task chrome. Desktop panes keep their independent reading position.
      if (window.innerWidth <= 800) {
        const targetId = next === "context" ? `sources-${task.id}` : `zhiyan-${task.id}-heading`;
        document.getElementById(targetId)?.scrollIntoView?.({ block: "start" });
      }
    });
  };

  const sourceView = workspace === "context";
  const workspaces: { key: TaskWorkspace; label: string }[] = [
    { key: "context", label: t("来源 · 主题") },
    { key: "work", label: t("知言 · 立言") },
  ];

  const taskActions = (
    <div className="workspace__actions task-card__actions">
      {opened ? null : (
        <button
          className="button button--quiet"
          type="button"
          aria-label={`${t("打开")} ${task.display_name}`}
          onClick={() => onOpen?.(task.id)}
        >
          {t("打开")}
        </button>
      )}
      {!editing ? (
        <button
          className="button button--quiet"
          type="button"
          aria-label={`${t("重命名")} ${task.display_name}`}
          onClick={() => {
            setName(task.display_name);
            setEditing(true);
          }}
        >
          {t("重命名")}
        </button>
      ) : null}
      <button
        className="button button--quiet"
        type="button"
        aria-label={`${t("删除")} ${task.display_name}`}
        aria-describedby={task.delete_disabled_reason ? `delete-reason-${task.id}` : undefined}
        disabled={!task.can_delete || deleting}
        onClick={() => setConfirmingDelete(true)}
      >
        {deleting ? t("删除中") : t("删除")}
      </button>
    </div>
  );

  return (
    <article
      ref={cardRef}
      className={`task-card ${opened ? "task-card--opened" : ""}`}
      aria-label={opened ? `${locale === "en" ? "Open task" : "已打开任务"} ${task.display_name}` : undefined}
      tabIndex={opened ? -1 : undefined}
    >
      <div className="task-card__number">#{task.number}</div>
      <div className="task-card__content">
        <div className="task-card__identity">
          {editing ? (
            <input
              className="task-card__rename-input"
              aria-label={t("任务名称")}
              value={name}
              autoFocus
              onFocus={(event) => event.currentTarget.select()}
              onChange={(event) => setName(event.target.value)}
              onBlur={() => void saveName()}
              onKeyDown={renameKeyDown}
            />
          ) : (
            <h3>{task.display_name}</h3>
          )}
          {opened ? (
            <div className="task-card__subline">
              <p className="task-card__meta">
                <span>{locale === "en" ? `${sourceCount} sources` : `共 ${sourceCount} 个来源`}</span>
                <span aria-hidden="true">·</span>
                <span>V{task.current_version_number}</span>
                <span aria-hidden="true">·</span>
                <span>{new Date(task.created_at).toLocaleDateString(dateLocale)}</span>
              </p>
              {taskActions}
            </div>
          ) : (
            <>
            <p className="task-card__source">{task.first_source_title}</p>
            <p className="task-card__meta">
              <span>{locale === "en" ? `${sourceCount} sources` : `共 ${sourceCount} 个来源`}</span>
              <span aria-hidden="true">·</span>
              <span>V{task.current_version_number}</span>
              <span aria-hidden="true">·</span>
              <span>{new Date(task.created_at).toLocaleDateString(dateLocale)}</span>
            </p>
            </>
          )}
          </div>
          {opened ? null : taskActions}
          {opened ? (
            <nav className="task-workspace-switcher" aria-label={t("任务视图")}>
              <ol>
                {workspaces.map((item) => (
                  <li key={item.key}>
                    <button
                      type="button"
                      aria-current={workspace === item.key ? "page" : undefined}
                      onClick={() => chooseWorkspace(item.key)}
                    >
                      <span className="task-workspace-switcher__label">{item.label}</span>
                    </button>
                  </li>
                ))}
              </ol>
            </nav>
          ) : null}
          {task.delete_disabled_reason ? (
            <p className="form-hint" id={`delete-reason-${task.id}`}>
              {domainMessage(task.delete_disabled_reason)}
            </p>
          ) : null}
          {error ? <p role="alert" className="form-error">{error}</p> : null}
        </div>
      <ConfirmDialog
        open={confirmingDelete}
        title={t("永久删除这个任务？")}
        body={t("任务及其工作内容将立即消失且无法恢复。")}
        confirmLabel={t("删除任务")}
        danger
        onOpenChange={setConfirmingDelete}
        onConfirm={() => void removeTask()}
      />
      {opened ? (
        <div className="task-detail">
          {sourceView ? (
            <section className="task-source-view" aria-label={t("来源 · 主题")}>
              {/* No pane heading: the tab above already says 来源 and the task
                  header already says 共 N 个来源 · V2. What this view needs is
                  the version it shows and what can be done to it, which is the
                  toolbar TaskSourceVersions owns. */}
              <TaskSourceVersions
                accessToken={accessToken}
                taskId={task.id}
                onVersionSelected={(versionId) => {
                  setSelectedVersionId(versionId);
                  setCapsuleSelection(null);
                }}
                onCurrentVersionChanged={(version) => {
                  setSelectedVersionId(version.id);
                  setCapsuleSelection(null);
                  setTask((current) => ({
                    ...current,
                    current_version_id: version.id,
                    current_version_number: version.number,
                    first_source_title: version.sources[0]?.title ?? current.first_source_title,
                    additional_source_count: Math.max(0, version.sources.length - 1),
                  }));
                }}
                onEditingChange={(editing) => onSourceEditingChange?.(task.id, editing)}
              />
            </section>
          ) : (
            <div className="task-workspace-split">

            <section
              className="task-workspace-pane"
              aria-labelledby={`zhiyan-${task.id}-heading`}
            >
              <header className="task-pane-heading">
                <h2 id={`zhiyan-${task.id}-heading`}>{t("知言")}</h2>
                <span>{zhiyanSummary}</span>
              </header>
              <TaskZhiyanArea
                accessToken={accessToken}
                taskId={task.id}
                versionId={selectedVersionId}
                onZhiyanState={noteZhiyanState}
                onCapsuleSelect={viewingCurrent ? selectCapsule : undefined}
              />
            </section>

            <section
              className="task-workspace-pane"
              aria-labelledby={`liyan-${task.id}-heading`}
            >
              <header className="task-pane-heading">
                <h2 id={`liyan-${task.id}-heading`}>{t("立言")}</h2>
                <span>{
                !viewingCurrent
                  ? t("历史版本只读")
                  : liyanReady ? t("可以撰写") : t("等待知言完成")
                }</span>
              </header>
              {viewingCurrent && liyanReady ? (
                <LiyanPanel
                  key={selectedVersionId}
                  userId={userId}
                  accessToken={accessToken}
                  taskId={task.id}
                  taskLabel={task.display_name}
                  capsuleSelection={capsuleSelection}
                  onPublicationChanged={onPublicationChanged}
                  onPublish={onPublish}
                />
              ) : (
                <p className="form-hint" role="status">
                  {!viewingCurrent
                    ? t("历史版本只读，恢复为当前版本后才能撰写立言。")
                    : domainMessage(zhiyan?.liyanReason ?? "知言状态读取中。")}
                </p>
              )}
            </section>
            </div>
          )}
        </div>
      ) : null}
    </article>
  );
}
