import type { Identity, TaskSummary } from "../auth/state";

type TaskWorkspaceProps = {
  identity: Identity;
  tasks: TaskSummary[];
  onSignOut(): Promise<void>;
};

export function TaskWorkspace({ identity, tasks, onSignOut }: TaskWorkspaceProps) {
  return (
    <section className="workspace workspace--tasks" aria-labelledby="task-list-heading">
      <div className="workspace__heading">
        <div>
          <p className="section-kicker">{identity.email}</p>
          <h2 id="task-list-heading">立言任务</h2>
        </div>
        <button className="button button--quiet" type="button" onClick={() => void onSignOut()}>
          退出登录
        </button>
      </div>
      {tasks.length === 0 ? (
        <div className="empty-state">
          <p className="empty-state__title">还没有立言任务</p>
          <p>创建入口将在下一阶段开放。</p>
        </div>
      ) : null}
    </section>
  );
}
