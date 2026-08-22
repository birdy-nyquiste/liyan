import { type FormEvent, useEffect, useRef, useState } from "react";

import { getCurrentTaskVersion, renameTask, type TaskVersionDetail } from "../api/client";
import type { TaskSummary } from "../auth/state";
import { ZhiyanPanel } from "./ZhiyanPanel";

export function TaskCard({
  task: initialTask,
  accessToken,
  opened = false,
  onOpen,
}: {
  task: TaskSummary;
  accessToken: string;
  opened?: boolean;
  onOpen?(taskId: string): void;
}) {
  const [task, setTask] = useState(initialTask);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState<TaskVersionDetail | null>(null);
  const cardRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (opened) cardRef.current?.focus();
  }, [opened]);

  useEffect(() => {
    if (!opened || version) return;
    let current = true;
    void getCurrentTaskVersion(accessToken, task.id)
      .then((loaded) => {
        if (current) setVersion(loaded);
      })
      .catch(() => {
        if (current) setError("任务版本加载失败，请稍后重试。");
      });
    return () => {
      current = false;
    };
  }, [opened, version, accessToken, task.id]);

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
      {opened && version ? (
        <div className="task-card__zhiyan">
          {version.source_revisions.map((revision) => (
            <ZhiyanPanel
              key={revision.id}
              accessToken={accessToken}
              sourceRevisionId={revision.id}
              sourceTitle={revision.title}
            />
          ))}
        </div>
      ) : null}
    </article>
  );
}
