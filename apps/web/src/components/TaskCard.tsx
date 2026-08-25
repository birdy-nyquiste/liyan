import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { ApiError, deleteTask, renameTask } from "../api/client";
import type { TaskSummary } from "../auth/state";
import { TaskZhiyanArea, type ZhiyanAreaState } from "./TaskZhiyanArea";
import { LiyanPanel } from "./LiyanPanel";
import type { CapsuleChoice, CapsuleSelection } from "./InstructionEditor";
import { TaskSourceVersions } from "./TaskSourceVersions";

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
  accessToken: string;
  opened?: boolean;
  onOpen?(taskId: string): void;
  onSourceEditingChange?(taskId: string, editing: boolean): void;
  onDelete?(taskId: string): void;
  onPublicationChanged?(): void;
  onPublish?(taskId: string, revisionId: string): void;
}) {
  const [task, setTask] = useState(initialTask);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [selectedVersionId, setSelectedVersionId] = useState(task.current_version_id);
  const [zhiyan, setZhiyan] = useState<ZhiyanAreaState | null>(null);
  const [focus, setFocus] = useState<"work" | "sources">(() =>
    window.localStorage.getItem(`liyan.taskStage.${initialTask.id}`) === "work"
      ? "work"
      : "sources",
  );
  const [capsuleSelection, setCapsuleSelection] = useState<CapsuleSelection | null>(null);
  const cardRef = useRef<HTMLElement>(null);

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

  async function saveName(event: FormEvent) {
    event.preventDefault();
    try {
      setTask(await renameTask(accessToken, task.id, name));
      setEditing(false);
      setError(null);
    } catch {
      setError("重命名失败，请重试。");
    }
  }

  async function removeTask() {
    if (!window.confirm("删除任务后将立即消失且无法恢复，确定删除吗？")) return;
    setDeleting(true);
    try {
      await deleteTask(accessToken, task.id);
      onDelete?.(task.id);
    } catch (thrown) {
      setError(
        thrown instanceof ApiError && thrown.detail
          ? thrown.detail
          : "删除失败，请稍后重试。",
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
    ? "读取中"
    : zhiyan.failed > 0
      ? `${zhiyan.failed} 个来源分析失败`
      : zhiyan.done === zhiyan.total
        ? `${zhiyan.total} 份报告已完成`
        : `${zhiyan.done} / ${zhiyan.total} 份报告完成`;

  const selectCapsule = (choice: CapsuleChoice) => {
    setCapsuleSelection((current) => ({ ...choice, nonce: (current?.nonce ?? 0) + 1 }));
  };

  const chooseFocus = (next: "work" | "sources") => {
    setFocus(next);
    window.localStorage.setItem(`liyan.taskStage.${task.id}`, next);
  };

  return (
    <article
      ref={cardRef}
      className={`task-card ${opened ? "task-card--opened" : ""}`}
      aria-label={opened ? `已打开任务 ${task.display_name}` : undefined}
      tabIndex={opened ? -1 : undefined}
    >
      <div className="task-card__number">#{task.number}</div>
      {editing ? (
        <form className="rename-form" onSubmit={(event) => void saveName(event)}>
          <label htmlFor={`task-name-${task.id}`}>任务名称</label>
          <input
            id={`task-name-${task.id}`}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <button className="button" type="submit">保存名称</button>
          {error ? (
            <p role="alert" className="form-error">{error}</p>
          ) : null}
        </form>
      ) : (
        <div className="task-card__content">
          <div>
            <h3>{task.display_name}</h3>
            <p className="task-card__source">{task.first_source_title}</p>
            <p className="task-card__meta">
              <span>共 {sourceCount} 个来源</span>
              <span aria-hidden="true">·</span>
              <span>V{task.current_version_number}</span>
              <span aria-hidden="true">·</span>
              <span>{new Date(task.created_at).toLocaleDateString("zh-CN")}</span>
            </p>
          </div>
          <div className="workspace__actions">
            {opened ? null : (
              <button
                className="button button--quiet"
                type="button"
                aria-label={`打开 ${task.display_name}`}
                onClick={() => onOpen?.(task.id)}
              >
                打开
              </button>
            )}
            <button
              className="button button--quiet"
              type="button"
              aria-label={`重命名 ${task.display_name}`}
              onClick={() => setEditing(true)}
            >
              重命名
            </button>
            <button
              className="button button--quiet"
              type="button"
              aria-label={`删除 ${task.display_name}`}
              aria-describedby={
                task.delete_disabled_reason ? `delete-reason-${task.id}` : undefined
              }
              disabled={!task.can_delete || deleting}
              onClick={() => void removeTask()}
            >
              {deleting ? "删除中" : "删除"}
            </button>
          </div>
          {opened ? (
            <div className="task-stage-tabs" role="tablist" aria-label="任务视图">
              <button
                type="button"
                role="tab"
                aria-selected={focus === "sources"}
                onClick={() => chooseFocus("sources")}
              >
                来源
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={focus === "work"}
                onClick={() => chooseFocus("work")}
              >
                知言 · 立言
              </button>
            </div>
          ) : null}
          {task.delete_disabled_reason ? (
            <p className="form-hint" id={`delete-reason-${task.id}`}>
              {task.delete_disabled_reason}
            </p>
          ) : null}
          {error ? <p role="alert" className="form-error">{error}</p> : null}
        </div>
      )}
      {opened ? (
        <div className="task-detail">
          {focus === "sources" ? (
            <section className="task-source-view" aria-labelledby={`sources-${task.id}-heading`}>
              <header className="task-pane-heading">
                <h2 id={`sources-${task.id}-heading`}>来源</h2>
                <span>{sourceCount} 个来源 · V{task.current_version_number}</span>
              </header>
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

            <section className="task-workspace-pane" aria-labelledby={`zhiyan-${task.id}-heading`}>
              <header className="task-pane-heading">
                <h2 id={`zhiyan-${task.id}-heading`}>知言</h2>
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

            <section className="task-workspace-pane" aria-labelledby={`liyan-${task.id}-heading`}>
              <header className="task-pane-heading">
                <h2 id={`liyan-${task.id}-heading`}>立言</h2>
                <span>{
                !viewingCurrent
                  ? "历史版本只读"
                  : liyanReady ? "可以撰写" : "等待知言完成"
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
                    ? "历史任务版本只读，恢复为当前版本后才能撰写立言。"
                    : zhiyan?.liyanReason ?? "知言状态读取中。"}
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
