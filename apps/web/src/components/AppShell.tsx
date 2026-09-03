import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import * as Tooltip from "@radix-ui/react-tooltip";
import { type InfiniteData, useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  FilePlus2,
  Languages,
  LogOut,
  ListTodo,
  Menu,
  MoreHorizontal,
  MonitorCog,
  MoonStar,
  Coins,
  Newspaper,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import { type KeyboardEvent, type ReactElement, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { toast } from "sonner";
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from "react-router-dom";

import { ApiError, deleteTask, getAccount, getTask, listTaskPage, renameTask, type AccessToken, type TaskListResponse } from "../api/client";
import type { Identity, TaskSummary } from "../auth/state";
import { InterfaceLocaleProvider, type InterfaceLocale } from "../interfaceLocale";
import { setHistoryGuard } from "../navigationGuard";
import { AccountPage } from "./AccountPage";
import { PublicationCenter } from "./PublicationCenter";
import { TaskCard } from "./TaskCard";
import { ConfirmDialog } from "./ConfirmDialog";
import { TaskCreationSession } from "./TaskCreationSession";

type Locale = InterfaceLocale;
type Theme = "light" | "dark" | "system";

const copy = {
  zh: {
    navigation: "主导航",
    newTask: "新建立言任务",
    // The rail's own label. The page it opens keeps the full term as its
    // heading, where there is room for it; in a 240px rail beside a list of
    // task names, 新建任务 is the same instruction with less to read.
    newTaskAction: "新建任务",
    publications: "发布",
    tasks: "任务",
    collapse: "折叠侧栏",
    expand: "展开侧栏",
    signOut: "退出登录",
    account: "账户",
    creditsRemaining: "剩余额度",
    language: "语言",
    languageValue: "中文",
    theme: "外观",
    themes: { light: "浅色", dark: "深色", system: "跟随系统" },
    preferences: "账户与偏好",
    signOutTitle: "退出登录？",
    signOutBody: "未保存的创建内容或来源修改会被丢弃，下次进入需要重新收取验证码。",
    rename: "重命名",
    remove: "删除",
    deleteTitle: "永久删除这个任务？",
    deleteBody: "任务及其工作内容将立即消失且无法恢复。",
    cancel: "取消",
    confirmDelete: "删除任务",
    empty: "还没有立言任务",
    missing: "找不到这个任务",
    loadingTask: "正在读取任务…",
    taskLoadFailed: "任务暂时无法读取，请重试。",
    retry: "重试",
    openNavigation: "打开导航",
    closeNavigation: "关闭导航",
    unavailable: "服务暂不可用，部分操作可能失败。",
    renamed: "任务名称已更新",
    renameFailed: "重命名失败，请稍后重试。",
    deleted: "任务已删除",
    deleteFailed: "删除失败，请稍后重试。",
    operations: "操作",
    loadMore: "加载更多",
    unsavedNavigation: "未保存的创建内容或来源修改会被丢弃，确定离开吗？",
    unsavedNavigationTitle: "离开这里？",
    leaveAnyway: "仍要离开",
  },
  en: {
    navigation: "Primary navigation",
    newTask: "New task",
    newTaskAction: "New task",
    publications: "Publications",
    tasks: "Tasks",
    collapse: "Collapse sidebar",
    expand: "Expand sidebar",
    signOut: "Sign out",
    account: "Account",
    creditsRemaining: "Remaining",
    language: "Language",
    languageValue: "English",
    theme: "Theme",
    themes: { light: "Light", dark: "Dark", system: "System" },
    preferences: "Account and preferences",
    signOutTitle: "Sign out?",
    signOutBody: "Unsaved creation content or source changes will be discarded, and signing back in needs a new email code.",
    rename: "Rename",
    remove: "Delete",
    deleteTitle: "Permanently delete this task?",
    deleteBody: "The task and its working content will disappear and cannot be recovered.",
    cancel: "Cancel",
    confirmDelete: "Delete task",
    empty: "No tasks yet",
    missing: "This task could not be found",
    loadingTask: "Loading task…",
    taskLoadFailed: "This task could not be loaded. Try again.",
    retry: "Try again",
    openNavigation: "Open navigation",
    closeNavigation: "Close navigation",
    unavailable: "The service is temporarily unavailable. Some actions may fail.",
    renamed: "Task name updated",
    renameFailed: "Rename failed. Please try again later.",
    deleted: "Task deleted",
    deleteFailed: "Delete failed. Please try again later.",
    operations: "actions",
    loadMore: "Load more",
    unsavedNavigation: "Unsaved creation content or source changes will be discarded. Leave this page?",
    unsavedNavigationTitle: "Leave this page?",
    leaveAnyway: "Leave anyway",
  },
} as const;

function storedValue<T extends string>(key: string, values: readonly T[], fallback: T): T {
  const value = window.localStorage.getItem(key) as T | null;
  return value && values.includes(value) ? value : fallback;
}

function usePreferences() {
  const [locale, setLocale] = useState<Locale>(() =>
    storedValue("liyan.locale", ["zh", "en"], "zh"),
  );
  const [theme, setTheme] = useState<Theme>(() =>
    storedValue("liyan.theme", ["light", "dark", "system"], "light"),
  );

  useEffect(() => {
    window.localStorage.setItem("liyan.locale", locale);
    document.documentElement.lang = locale === "zh" ? "zh-CN" : "en";
  }, [locale]);

  useEffect(() => {
    window.localStorage.setItem("liyan.theme", theme);
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return { locale, setLocale, theme, setTheme, text: copy[locale] };
}

function RailTooltip({ label, show, children }: { label: string; show: boolean; children: ReactElement }) {
  if (!show) return children;
  return (
    <Tooltip.Root>
      <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content className="rail-tooltip" side="right" sideOffset={8}>
          {label}
          <Tooltip.Arrow className="rail-tooltip__arrow" />
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

function SidebarTask({
  task,
  active,
  collapsed,
  text,
  onRenamed,
  onDeleted,
  accessToken,
  onNavigate,
}: {
  task: TaskSummary;
  active: boolean;
  collapsed: boolean;
  text: (typeof copy)[Locale];
  accessToken: AccessToken;
  onRenamed(task: TaskSummary): void;
  onDeleted(taskId: string): void;
  onNavigate(to: string): boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const cancelRename = useRef(false);

  async function saveRename() {
    if (cancelRename.current) {
      cancelRename.current = false;
      return;
    }
    const normalized = name.trim().replace(/\s+/g, " ");
    if (!normalized) {
      setName(task.display_name);
      setEditing(false);
      return;
    }
    if (normalized === task.display_name) {
      setEditing(false);
      return;
    }
    setBusy(true);
    try {
      onRenamed(await renameTask(accessToken, task.id, normalized));
      setEditing(false);
      setMutationError(null);
      toast.success(text.renamed);
    } catch {
      setMutationError(text.renameFailed);
    } finally {
      setBusy(false);
    }
  }

  function renameKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveRename();
    }
    if (event.key === "Escape") {
      cancelRename.current = true;
      setName(task.display_name);
      setEditing(false);
    }
  }

  return (
    <div className="sidebar-task" data-active={active || undefined}>
      {editing && !collapsed ? (
        <input
          className="sidebar-task__input"
          aria-label={`${text.rename} ${task.display_name}`}
          value={name}
          autoFocus
          disabled={busy}
          onFocus={(event) => event.currentTarget.select()}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => void saveRename()}
          onKeyDown={renameKeyDown}
        />
      ) : (
        <RailTooltip label={task.display_name} show={collapsed}>
          <Link
            className="sidebar-task__link"
            to={`/task/${task.id}`}
            aria-label={collapsed ? task.display_name : undefined}
            aria-current={active ? "page" : undefined}
            onClick={(event) => {
              if (!onNavigate(`/task/${task.id}`)) event.preventDefault();
            }}
          >
            {task.display_name}
          </Link>
        </RailTooltip>
      )}
      {!collapsed ? (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className="icon-button sidebar-task__menu" aria-label={`${task.display_name} ${text.operations}`}>
            <MoreHorizontal size={17} aria-hidden="true" />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="menu-content" sideOffset={6} align="start">
              <DropdownMenu.Item className="menu-item" onSelect={() => setEditing(true)}>
                <Pencil size={15} aria-hidden="true" /> {text.rename}
              </DropdownMenu.Item>
              <DropdownMenu.Item
                className="menu-item menu-item--danger"
                disabled={!task.can_delete}
                onSelect={() => setDeleteOpen(true)}
              >
                <Trash2 size={15} aria-hidden="true" /> {text.remove}
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      ) : null}

      <AlertDialog.Root open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialog.Portal>
          <AlertDialog.Overlay className="dialog-overlay" />
          <AlertDialog.Content className="dialog-content">
            <AlertDialog.Title>{text.deleteTitle}</AlertDialog.Title>
            <AlertDialog.Description>{text.deleteBody}</AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel className="button button--quiet">{text.cancel}</AlertDialog.Cancel>
              <button
                className="button button--danger"
                type="button"
                onClick={() => {
                  setBusy(true);
                  void deleteTask(accessToken, task.id)
                    .then(() => {
                      setMutationError(null);
                      setDeleteOpen(false);
                      onDeleted(task.id);
                      toast.success(text.deleted);
                    })
                    .catch(() => setMutationError(text.deleteFailed))
                    .finally(() => setBusy(false));
                }}
              >
                {text.confirmDelete}
              </button>
            </div>
            {mutationError ? <p className="form-error" role="alert">{mutationError}</p> : null}
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </div>
  );
}

function LoadMoreTasks({ onVisible, label }: { onVisible(): void; label: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onVisible();
    }, { rootMargin: "120px" });
    observer.observe(node);
    return () => observer.disconnect();
  }, [onVisible]);
  return (
    <div ref={ref} className="sidebar-load-trigger">
      <button className="sidebar-load-more" type="button" onClick={onVisible}>{label}</button>
    </div>
  );
}

function Sidebar({
  identity,
  accessToken,
  tasks,
  collapsed,
  currentTaskId,
  theme,
  text,
  onCollapse,
  onLocale,
  onTheme,
  onRenamed,
  onDeleted,
  onSignOut,
  onNavigate,
  hasMore,
  onLoadMore,
}: {
  identity: Identity;
  accessToken: AccessToken;
  tasks: TaskSummary[];
  collapsed: boolean;
  currentTaskId: string | null;
  theme: Theme;
  text: (typeof copy)[Locale];
  onCollapse(): void;
  onLocale(): void;
  onTheme(): void;
  onRenamed(task: TaskSummary): void;
  onDeleted(taskId: string): void;
  onSignOut(): void;
  onNavigate(to: string): boolean;
  hasMore: boolean;
  onLoadMore(): void;
}) {
  const [tasksOpen, setTasksOpen] = useState(() =>
    storedValue("liyan.tasksOpen", ["true", "false"], "true") === "true",
  );
  // The three preference actions are consulted rarely; the address they belong
  // to is what a writer checks. So the address holds the foot of the rail and
  // the actions fold into it.
  const [accountOpen, setAccountOpen] = useState(() =>
    storedValue("liyan.accountOpen", ["true", "false"], "false") === "true",
  );
  // Signing out is one unlabelled icon away from the avatar in the rail, and it
  // costs a fresh email code to undo.
  const [signOutOpen, setSignOutOpen] = useState(false);
  // Refetched on window focus by default, which is when a user coming back from
  // a run wants to see what it cost.
  const account = useQuery({
    queryKey: ["account", accessToken],
    queryFn: () => getAccount(accessToken),
  });
  const creditsLabel = account.data ? account.data.remaining_credits.toLocaleString() : "—";
  const themeIcon =
    theme === "light" ? <Sun size={18} />
    : theme === "dark" ? <MoonStar size={18} />
    : <MonitorCog size={18} />;

  return (
    <Tooltip.Provider delayDuration={250}>
    <aside className="app-sidebar" data-collapsed={collapsed || undefined}>
      <div className="sidebar-brand">
        <RailTooltip label={collapsed ? text.expand : text.collapse} show>
          <button className="icon-button sidebar-collapse" type="button" aria-label={collapsed ? text.expand : text.collapse} onClick={onCollapse}>
            {collapsed ? <PanelLeftOpen size={20} /> : <PanelLeftClose size={20} />}
          </button>
        </RailTooltip>
        <span className="sidebar-brand__identity">
          <img src="/liyan-mark.svg" alt="" />
          <strong>立言阁</strong>
        </span>
      </div>

      <nav className="sidebar-primary" aria-label={text.navigation}>
        <RailTooltip label={text.newTaskAction} show={collapsed}>
          {/*
            `end`, so this is current only at /task itself. Without it React
            Router counts /task/:taskId as a descendant and the rail showed
            新建任务 as the selected place while the writer was reading a task —
            two things selected at once, and the wrong one of them highlighted.
          */}
          <NavLink end aria-label={text.newTaskAction} className="sidebar-nav-link" to="/task" onClick={(event) => { if (!onNavigate("/task")) event.preventDefault(); }}>
            <FilePlus2 size={19} aria-hidden="true" /> <span>{text.newTaskAction}</span>
          </NavLink>
        </RailTooltip>
        <RailTooltip label={text.publications} show={collapsed}>
          <NavLink aria-label={text.publications} className="sidebar-nav-link" to="/publications" onClick={(event) => { if (!onNavigate("/publications")) event.preventDefault(); }}>
            <Newspaper size={19} aria-hidden="true" /> <span>{text.publications}</span>
          </NavLink>
        </RailTooltip>
      </nav>

      <section className="sidebar-tasks" aria-label={text.tasks}>
        <RailTooltip label={text.tasks} show={collapsed}>
          <button
            className="sidebar-nav-link sidebar-section-toggle"
            type="button"
            aria-expanded={!collapsed && tasksOpen}
            onClick={() => {
              if (collapsed) {
                if (!tasksOpen) {
                  setTasksOpen(true);
                  window.localStorage.setItem("liyan.tasksOpen", "true");
                }
                onCollapse();
                return;
              }
              const next = !tasksOpen;
              setTasksOpen(next);
              window.localStorage.setItem("liyan.tasksOpen", String(next));
            }}
          >
            <ListTodo size={19} aria-hidden="true" />
            <span>{text.tasks}</span>
            {tasksOpen ? <ChevronDown className="sidebar-section-toggle__caret" size={14} aria-hidden="true" /> : <ChevronRight className="sidebar-section-toggle__caret" size={14} aria-hidden="true" />}
          </button>
        </RailTooltip>
        {tasksOpen || collapsed ? (
          <div className="sidebar-task-list" aria-hidden={collapsed || undefined} inert={collapsed}>
            {tasks.map((task) => (
              <SidebarTask
                key={task.id}
                task={task}
                active={task.id === currentTaskId}
                collapsed={collapsed}
                text={text}
                accessToken={accessToken}
                onRenamed={onRenamed}
                onDeleted={onDeleted}
                onNavigate={onNavigate}
              />
            ))}
            {hasMore && !collapsed ? (
              <LoadMoreTasks onVisible={onLoadMore} label={text.loadMore} />
            ) : null}
            {!collapsed && tasks.length === 0 ? <p className="sidebar-empty">{text.empty}</p> : null}
          </div>
        ) : null}
      </section>

      <div className="sidebar-account">
        <div className="sidebar-account__group" id="sidebar-preferences" data-open={accountOpen || undefined}>
          <div className="sidebar-account__actions" aria-hidden={!accountOpen || undefined}>
        <RailTooltip label={`${text.theme}: ${text.themes[theme]}`} show={collapsed}>
          <button aria-label={`${text.theme}: ${text.themes[theme]}`} className="sidebar-account__action" type="button" onClick={onTheme} tabIndex={accountOpen ? undefined : -1}>
            {themeIcon}
            <span>{text.theme}</span>
            <span className="sidebar-account__value">{text.themes[theme]}</span>
          </button>
        </RailTooltip>
        <RailTooltip label={`${text.language}: ${text.languageValue}`} show={collapsed}>
          <button aria-label={`${text.language}: ${text.languageValue}`} className="sidebar-account__action" type="button" onClick={onLocale} tabIndex={accountOpen ? undefined : -1}>
            <Languages size={18} />
            <span>{text.language}</span>
            <span className="sidebar-account__value">{text.languageValue}</span>
          </button>
        </RailTooltip>
        <RailTooltip label={`${text.account}: ${text.creditsRemaining} ${creditsLabel}`} show={collapsed}>
          {/*
            A bare integer, and it lives here rather than in the rail because a
            user meets it at a refusal, not while they work. The group already
            renders a label with a value beside it, which is the shape a balance
            wants.
          */}
          <NavLink
            aria-label={`${text.account}: ${text.creditsRemaining} ${creditsLabel}`}
            className="sidebar-account__action"
            to="/account"
            tabIndex={accountOpen ? undefined : -1}
            onClick={(event) => { if (!onNavigate("/account")) event.preventDefault(); }}
          >
            <Coins size={18} />
            <span>{text.account}</span>
            <span className="sidebar-account__value">
              <span className="sidebar-account__value-label">{text.creditsRemaining}</span>
              {creditsLabel}
            </span>
          </NavLink>
        </RailTooltip>
        <RailTooltip label={text.signOut} show={collapsed}>
          <button aria-label={text.signOut} className="sidebar-account__action" type="button" onClick={() => setSignOutOpen(true)} tabIndex={accountOpen ? undefined : -1}>
            <LogOut size={18} /> <span>{text.signOut}</span>
          </button>
        </RailTooltip>

        <AlertDialog.Root open={signOutOpen} onOpenChange={setSignOutOpen}>
          <AlertDialog.Portal>
            <AlertDialog.Overlay className="dialog-overlay" />
            <AlertDialog.Content className="dialog-content">
              <AlertDialog.Title>{text.signOutTitle}</AlertDialog.Title>
              <AlertDialog.Description>{text.signOutBody}</AlertDialog.Description>
              <div className="dialog-actions">
                <AlertDialog.Cancel className="button button--quiet">{text.cancel}</AlertDialog.Cancel>
                <button className="button button--danger" type="button" onClick={onSignOut}>
                  {text.signOut}
                </button>
              </div>
            </AlertDialog.Content>
          </AlertDialog.Portal>
        </AlertDialog.Root>
          </div>
        </div>

        <RailTooltip label={identity.email} show={collapsed}>
          <button
            className="sidebar-identity"
            type="button"
            aria-label={`${text.preferences}: ${identity.email}`}
            aria-expanded={accountOpen}
            aria-controls="sidebar-preferences"
            onClick={() => {
              const next = !accountOpen;
              setAccountOpen(next);
              window.localStorage.setItem("liyan.accountOpen", String(next));
            }}
          >
            <span className="avatar" aria-hidden="true">{identity.email.charAt(0).toUpperCase()}</span>
            <span className="sidebar-identity__email">{identity.email}</span>
            <ChevronDown className="sidebar-identity__caret" size={15} aria-hidden="true" />
          </button>
        </RailTooltip>
      </div>
    </aside>
    </Tooltip.Provider>
  );
}

function TaskRoute({
  tasks,
  identity,
  accessToken,
  onDeleted,
  onSourceEditing,
  missingLabel,
  loadingLabel,
  failedLabel,
  retryLabel,
}: {
  tasks: TaskSummary[];
  identity: Identity;
  accessToken: AccessToken;
  onDeleted(taskId: string): void;
  onSourceEditing(dirty: boolean): void;
  missingLabel: string;
  loadingLabel: string;
  failedLabel: string;
  retryLabel: string;
}) {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const cached = tasks.find((candidate) => candidate.id === taskId);
  const taskQuery = useQuery({
    queryKey: ["task", accessToken, taskId],
    queryFn: () => getTask(accessToken, taskId!),
    enabled: Boolean(taskId && !cached),
    retry: (failureCount, error) =>
      !(error instanceof ApiError && error.status === 404) && failureCount < 2,
  });
  const task = cached ?? taskQuery.data;
  if (!task) {
    if (taskQuery.isPending) {
      return <div className="route-empty" role="status"><h1>{loadingLabel}</h1></div>;
    }
    const taskError = taskQuery.error;
    if (taskError instanceof ApiError && taskError.status === 404) {
      return <div className="route-empty"><h1>{missingLabel}</h1></div>;
    }
    return (
      <div className="route-empty">
        <h1>{failedLabel}</h1>
        <button className="button" type="button" onClick={() => void taskQuery.refetch()}>
          {retryLabel}
        </button>
      </div>
    );
  }
  return (
    <TaskCard
      // Remounted per task, not reused. `TaskCard` copies the task it is given
      // into state, so a reused instance keeps showing the one it opened with:
      // every 立言任务 rendered whatever was clicked first. Its editing, naming
      // and selected-version state belong to one task too, and should not
      // survive into another.
      key={task.id}
      task={task}
      userId={identity.id}
      accessToken={accessToken}
      opened
      onDelete={onDeleted}
      onPublish={(selectedTaskId, revisionId) => navigate(`/publications?taskId=${selectedTaskId}&revisionId=${revisionId}`)}
      onSourceEditingChange={(_, dirty) => onSourceEditing(dirty)}
    />
  );
}

export function AppShell({
  identity,
  accessToken,
  initialTasks,
  serviceUnavailable = false,
  onSignOut,
}: {
  identity: Identity;
  accessToken: AccessToken;
  initialTasks: TaskSummary[];
  serviceUnavailable?: boolean;
  onSignOut(): Promise<void>;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const preferences = usePreferences();
  const [collapsed, setCollapsed] = useState(() => window.localStorage.getItem("liyan.sidebarCollapsed") === "true");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [creationDirty, setCreationDirty] = useState(false);
  const [sourceDirty, setSourceDirty] = useState(false);
  /**
   * What a blocked navigation is waiting on. Held as a thunk rather than run
   * immediately: the writer has to answer first, and the answer arrives from a
   * dialog rather than from `window.confirm` — which a browser may suppress,
   * answering "stay here" on their behalf and trapping them on the page.
   */
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
  const dirty = creationDirty || sourceDirty;
  const allowNavigation = useCallback(() => {
    setCreationDirty(false);
    setSourceDirty(false);
  }, []);
  const requestNavigation = useCallback((proceed: () => void) => {
    if (!dirty) return true;
    setPendingNavigation(() => proceed);
    return false;
  }, [dirty]);

  useLayoutEffect(() => {
    if (!dirty) {
      setHistoryGuard(null);
      return;
    }
    setHistoryGuard({
      onBlocked: (replay) => setPendingNavigation(() => replay),
      protectedState: window.history.state,
      protectedUrl: window.location.href,
    });
    return () => setHistoryGuard(null);
  }, [dirty]);
  const taskQuery = useInfiniteQuery({
    queryKey: ["tasks", accessToken],
    queryFn: ({ pageParam }) => listTaskPage(accessToken, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    initialData: {
      pages: [{ items: initialTasks, next_cursor: null }],
      pageParams: [null],
    },
    initialDataUpdatedAt: 0,
  });
  const tasks = taskQuery.data.pages.flatMap((page) => page.items);
  const currentTaskId = /^\/task\/([^/]+)$/.exec(location.pathname)?.[1] ?? null;

  function promoteTask(task: TaskSummary) {
    queryClient.setQueryData<InfiniteData<TaskListResponse, string | null>>(
      ["tasks", accessToken],
      (current) => current && ({
        ...current,
        pages: current.pages.map((page, index) => ({
          ...page,
          items: index === 0
            ? [task, ...page.items.filter((item) => item.id !== task.id)]
            : page.items.filter((item) => item.id !== task.id),
        })),
      }),
    );
  }

  function removeTask(taskId: string) {
    queryClient.setQueryData<InfiniteData<TaskListResponse, string | null>>(
      ["tasks", accessToken],
      (current) => current && ({
        ...current,
        pages: current.pages.map((page) => ({
          ...page,
          items: page.items.filter((item) => item.id !== taskId),
        })),
      }),
    );
  }

  function deleted(taskId: string) {
    removeTask(taskId);
    if (currentTaskId === taskId) navigate("/task");
  }

  /*
   * Collapsing to a rail is a desktop preference, and it is persisted — so the
   * drawer, which reuses this, was opening as a column of unlabelled icons for
   * anyone who had ever collapsed the sidebar on a wide screen. There is no rail
   * on a phone to collapse into and, now that the drawer hides the collapse
   * button, no way back out of it either. The drawer always renders expanded.
   */
  const sidebarFor = (isCollapsed: boolean) => (
    <Sidebar
      identity={identity}
      accessToken={accessToken}
      tasks={tasks}
      collapsed={isCollapsed}
      currentTaskId={currentTaskId}
      theme={preferences.theme}
      text={preferences.text}
      onCollapse={() => {
        const next = !collapsed;
        setCollapsed(next);
        window.localStorage.setItem("liyan.sidebarCollapsed", String(next));
      }}
      onLocale={() => preferences.setLocale(preferences.locale === "zh" ? "en" : "zh")}
      onTheme={() => preferences.setTheme(preferences.theme === "light" ? "dark" : preferences.theme === "dark" ? "system" : "light")}
      onRenamed={promoteTask}
      onDeleted={deleted}
      onSignOut={() => {
        if (requestNavigation(() => void onSignOut())) void onSignOut();
      }}
      onNavigate={(to) => {
        const allowed = requestNavigation(() => {
          setMobileOpen(false);
          navigate(to);
        });
        if (allowed) setMobileOpen(false);
        return allowed;
      }}
      hasMore={taskQuery.hasNextPage}
      onLoadMore={() => void taskQuery.fetchNextPage()}
    />
  );
  const sidebar = sidebarFor(collapsed);

  return (
    <InterfaceLocaleProvider locale={preferences.locale}>
    <div className="app-frame" data-sidebar-collapsed={collapsed || undefined}>
      <div className="desktop-sidebar">{sidebar}</div>
      <ConfirmDialog
        open={pendingNavigation !== null}
        title={preferences.text.unsavedNavigationTitle}
        body={preferences.text.unsavedNavigation}
        confirmLabel={preferences.text.leaveAnyway}
        danger
        onOpenChange={(open) => { if (!open) setPendingNavigation(null); }}
        onConfirm={() => {
          const proceed = pendingNavigation;
          setPendingNavigation(null);
          allowNavigation();
          proceed?.();
        }}
      />
      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Trigger className="mobile-menu-button" aria-label={preferences.text.openNavigation}>
          <Menu size={22} />
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="mobile-drawer">
            <Dialog.Title className="sr-only">{preferences.text.navigation}</Dialog.Title>
            <Dialog.Close className="icon-button mobile-drawer__close" aria-label={preferences.text.closeNavigation}><X size={20} /></Dialog.Close>
            {sidebarFor(false)}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <main className="route-surface">
        {serviceUnavailable ? <div className="service-banner" role="alert">{preferences.text.unavailable}</div> : null}
        <Routes>
          <Route path="/" element={<Navigate to="/task" replace />} />
          <Route
            path="/task"
            element={
              <div className="creation-page">
                <header className="page-heading">
                  <h1>{preferences.text.newTask}</h1>
                </header>
                <TaskCreationSession
                  accessToken={accessToken}
                  onDirtyChange={setCreationDirty}
                  onCreated={(task) => {
                    setCreationDirty(false);
                    promoteTask(task);
                    window.setTimeout(() => navigate(`/task/${task.id}`), 0);
                  }}
                />
              </div>
            }
          />
          <Route
            path="/task/:taskId"
            element={
              <TaskRoute
                tasks={tasks}
                identity={identity}
                accessToken={accessToken}
                onDeleted={deleted}
                onSourceEditing={setSourceDirty}
                missingLabel={preferences.text.missing}
                loadingLabel={preferences.text.loadingTask}
                failedLabel={preferences.text.taskLoadFailed}
                retryLabel={preferences.text.retry}
              />
            }
          />
          <Route
            path="/publications"
            element={
              <PublicationCenter
                userId={identity.id}
                accessToken={accessToken}
                onOpenTask={(taskId) => navigate(`/task/${taskId}`)}
                initialTaskId={new URLSearchParams(location.search).get("taskId")}
                initialRevisionId={new URLSearchParams(location.search).get("revisionId")}
                onPublicationChanged={() => void taskQuery.refetch()}
              />
            }
          />
          <Route path="/account" element={<AccountPage accessToken={accessToken} />} />
          <Route path="*" element={<Navigate to="/task" replace />} />
        </Routes>
      </main>
    </div>
    </InterfaceLocaleProvider>
  );
}
