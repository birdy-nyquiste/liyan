import { type FormEvent, useEffect, useRef, useState } from "react";

import { renameTask } from "../api/client";
import type { TaskSummary } from "../auth/state";
import { TaskZhiyanArea } from "./TaskZhiyanArea";
import { LiyanPanel } from "./LiyanPanel";
import { TaskSourceVersions } from "./TaskSourceVersions";

export function TaskCard({
  task: initialTask,
  userId,
  accessToken,
  opened = false,
  onOpen,
  onSourceEditingChange,
}: {
  task: TaskSummary;
  userId: string;
  accessToken: string;
  opened?: boolean;
  onOpen?(taskId: string): void;
  onSourceEditingChange?(taskId: string, editing: boolean): void;
}) {
  const [task, setTask] = useState(initialTask);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [error, setError] = useState<string | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState(task.current_version_id);
  const [liyanReady, setLiyanReady] = useState(false);
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (opened) cardRef.current?.focus();
  }, [opened]);

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
            <p>
              另有 {task.additional_source_count} 个来源 · {new Date(task.created_at).toLocaleDateString("zh-CN")}
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
          </div>
        </div>
      )}
      {opened ? (
        <div className="task-detail">
          <TaskSourceVersions
            accessToken={accessToken}
            taskId={task.id}
            onVersionSelected={(versionId) => {
              setSelectedVersionId(versionId);
              setLiyanReady(false);
            }}
            onCurrentVersionChanged={(version) => {
              setSelectedVersionId(version.id);
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
          <TaskZhiyanArea
            accessToken={accessToken}
            taskId={task.id}
            versionId={selectedVersionId}
            showLiyanGate={!liyanReady}
            onLiyanAvailabilityChange={setLiyanReady}
          />
          {selectedVersionId === task.current_version_id && liyanReady ? (
            <LiyanPanel userId={userId} accessToken={accessToken} taskId={task.id} />
          ) : null}
        </div>
      ) : null}
    </article>
  );
}
