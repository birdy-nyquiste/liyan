import { useState } from "react";

import type { Identity, TaskSummary } from "../auth/state";
import { TaskCard } from "./TaskCard";
import { TaskCreationSession } from "./TaskCreationSession";

type TaskWorkspaceProps = {
  identity: Identity;
  accessToken: string;
  tasks: TaskSummary[];
  onTaskCreated(task: TaskSummary): void;
  onSignOut(): Promise<void>;
};

export function TaskWorkspace({
  identity,
  accessToken,
  tasks,
  onTaskCreated,
  onSignOut,
}: TaskWorkspaceProps) {
  const [creating, setCreating] = useState(false);
  const [creationDirty, setCreationDirty] = useState(false);
  const [openedTaskId, setOpenedTaskId] = useState<string | null>(null);

  const taskCreated = (task: TaskSummary) => {
    setOpenedTaskId(task.id);
    onTaskCreated(task);
  };

  const attemptSignOut = () => {
    if (
      !creationDirty ||
      window.confirm("未完成的创建内容不会保存，确定退出登录吗？")
    ) {
      void onSignOut();
    }
  };

  return (
    <section className="workspace workspace--tasks" aria-labelledby="task-list-heading">
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
          <button className="button button--quiet" type="button" onClick={attemptSignOut}>
            退出登录
          </button>
        </div>
      </div>
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
            accessToken={accessToken}
            opened={task.id === openedTaskId}
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
