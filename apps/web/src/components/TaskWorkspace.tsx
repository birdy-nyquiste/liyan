import { useCallback, useState } from "react";

import { listTasks } from "../api/client";
import type { Identity, TaskSummary } from "../auth/state";
import { TaskCard } from "./TaskCard";
import { PublicationCenter } from "./PublicationCenter";
import { TaskCreationSession } from "./TaskCreationSession";

type TaskWorkspaceProps = {
  identity: Identity;
  accessToken: string;
  tasks: TaskSummary[];
  onTaskCreated(task: TaskSummary): void;
  onTaskDeleted?(taskId: string): void;
  onTasksChanged?(tasks: TaskSummary[]): void;
  onSignOut(): Promise<void>;
};

export function TaskWorkspace({
  identity,
  accessToken,
  tasks,
  onTaskCreated,
  onTaskDeleted,
  onTasksChanged,
  onSignOut,
}: TaskWorkspaceProps) {
  const [creating, setCreating] = useState(false);
  const [creationDirty, setCreationDirty] = useState(false);
  const [openedTaskId, setOpenedTaskId] = useState<string | null>(null);
  const [publicationCenterOpen, setPublicationCenterOpen] = useState(false);
  const [sourceEditingTaskIds, setSourceEditingTaskIds] = useState<Set<string>>(new Set());

  const refreshTasks = useCallback(async () => {
    if (!onTasksChanged) return;
    try {
      onTasksChanged(await listTasks(accessToken));
    } catch {
      // The delete endpoint still rechecks this capability; a refresh failure
      // cannot permit deletion while a publication is running.
    }
  }, [accessToken, onTasksChanged]);

  const taskCreated = (task: TaskSummary) => {
    setOpenedTaskId(task.id);
    onTaskCreated(task);
  };

  const openTask = (taskId: string) => {
    if (
      sourceEditingTaskIds.size > 0
      && !sourceEditingTaskIds.has(taskId)
      && !window.confirm("未保存的来源修改会被丢弃，确定离开当前任务吗？")
    ) return;
    setOpenedTaskId(taskId);
  };

  const attemptSignOut = () => {
    if (
      (!creationDirty && sourceEditingTaskIds.size === 0) ||
      window.confirm("未完成的创建内容或来源修改不会保存，确定退出登录吗？")
    ) {
      void onSignOut();
    }
  };

  return (
    <section
      className={`workspace workspace--tasks ${openedTaskId ? "workspace--wide" : ""}`}
      aria-labelledby="task-list-heading"
    >
      <div className="workspace__heading">
        <div>
          <p className="section-kicker">{identity.email}</p>
          <h2 id="task-list-heading">立言任务</h2>
        </div>
        <div className="workspace__actions">
          <button
            className="button"
            type="button"
            disabled={creating}
            onClick={() => setCreating(true)}
          >
            新建立言任务
          </button>
          <button
            className="button button--quiet"
            type="button"
            onClick={() => setPublicationCenterOpen((open) => !open)}
          >
            发布中心
          </button>
          <button className="button button--quiet" type="button" onClick={attemptSignOut}>
            退出登录
          </button>
        </div>
      </div>
      {publicationCenterOpen ? (
        <PublicationCenter
          userId={identity.id}
          accessToken={accessToken}
          onPublicationChanged={() => void refreshTasks()}
          onClose={() => {
            setPublicationCenterOpen(false);
            void refreshTasks();
          }}
        />
      ) : null}
      {creating ? (
        <TaskCreationSession
          accessToken={accessToken}
          onCreated={taskCreated}
          onClose={() => setCreating(false)}
          onDirtyChange={setCreationDirty}
        />
      ) : null}
      <div className="task-list">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            userId={identity.id}
            accessToken={accessToken}
            opened={task.id === openedTaskId}
            onOpen={openTask}
            onDelete={(taskId) => {
              setOpenedTaskId((current) => current === taskId ? null : current);
              setSourceEditingTaskIds((current) => {
                const next = new Set(current);
                next.delete(taskId);
                return next;
              });
              onTaskDeleted?.(taskId);
            }}
            onPublicationChanged={() => void refreshTasks()}
            onSourceEditingChange={(taskId, editing) => setSourceEditingTaskIds((current) => {
              const next = new Set(current);
              if (editing) next.add(taskId);
              else next.delete(taskId);
              return next;
            })}
          />
        ))}
      </div>
      {tasks.length === 0 && !creating ? (
        <div className="empty-state">
          <p className="empty-state__title">还没有立言任务</p>
          <p>粘贴一个来源，创建第一项立言任务。</p>
        </div>
      ) : null}
    </section>
  );
}
