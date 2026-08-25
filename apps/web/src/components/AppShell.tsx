import * as AlertDialog from "@radix-ui/react-alert-dialog";
import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BookOpenText,
  ChevronLeft,
  ChevronRight,
  FilePlus2,
  Languages,
  LogOut,
  Menu,
  MoreHorizontal,
  MoonStar,
  Newspaper,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import { type KeyboardEvent, useEffect, useRef, useState } from "react";
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

import { deleteTask, getTask, listTaskPage, renameTask } from "../api/client";
import type { Identity, TaskSummary } from "../auth/state";
import { PublicationCenter } from "./PublicationCenter";
import { TaskCard } from "./TaskCard";
import { TaskCreationSession } from "./TaskCreationSession";

type Locale = "zh" | "en";
type Theme = "light" | "dark" | "system";

const copy = {
  zh: {
    navigation: "主导航",
    newTask: "新建立言任务",
    publications: "发布",
    tasks: "任务",
    collapse: "折叠侧栏",
    expand: "展开侧栏",
    signOut: "退出登录",
    language: "中文",
    rename: "重命名",
    remove: "删除",
    deleteTitle: "永久删除这个任务？",
    deleteBody: "任务及其工作内容将立即消失且无法恢复。",
    cancel: "取消",
    confirmDelete: "删除任务",
    empty: "还没有立言任务",
    missing: "找不到这个任务",
  },
  en: {
    navigation: "Primary navigation",
    newTask: "New task",
    publications: "Publications",
    tasks: "Tasks",
    collapse: "Collapse sidebar",
    expand: "Expand sidebar",
    signOut: "Sign out",
    language: "English",
    rename: "Rename",
    remove: "Delete",
    deleteTitle: "Permanently delete this task?",
    deleteBody: "The task and its working content will disappear and cannot be recovered.",
    cancel: "Cancel",
    confirmDelete: "Delete task",
    empty: "No tasks yet",
    missing: "This task could not be found",
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
  accessToken: string;
  onRenamed(task: TaskSummary): void;
  onDeleted(taskId: string): void;
  onNavigate(): boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.display_name);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [busy, setBusy] = useState(false);
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
        <Link
          className="sidebar-task__link"
          to={`/task/${task.id}`}
          title={collapsed ? task.display_name : undefined}
          aria-current={active ? "page" : undefined}
          onClick={(event) => {
            if (!onNavigate()) event.preventDefault();
          }}
        >
          {collapsed ? <BookOpenText size={19} aria-hidden="true" /> : task.display_name}
        </Link>
      )}
      {!collapsed ? (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger className="icon-button sidebar-task__menu" aria-label={`${task.display_name} 操作`}>
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
              <AlertDialog.Action
                className="button button--danger"
                onClick={() => {
                  setBusy(true);
                  void deleteTask(accessToken, task.id)
                    .then(() => onDeleted(task.id))
                    .finally(() => setBusy(false));
                }}
              >
                {text.confirmDelete}
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </div>
  );
}

function LoadMoreTasks({ onVisible }: { onVisible(): void }) {
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
      <button className="sidebar-load-more" type="button" onClick={onVisible}>加载更多</button>
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
  accessToken: string;
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
  onNavigate(): boolean;
  hasMore: boolean;
  onLoadMore(): void;
}) {
  const [tasksOpen, setTasksOpen] = useState(() =>
    storedValue("liyan.tasksOpen", ["true", "false"], "true") === "true",
  );
  const themeIcon = theme === "light" ? <Sun size={18} /> : <MoonStar size={18} />;

  return (
    <aside className="app-sidebar" data-collapsed={collapsed || undefined}>
      <div className="sidebar-brand">
        <img src="/liyan-mark.svg" alt="" />
        {!collapsed ? <strong>立言阁</strong> : null}
        <button className="icon-button sidebar-collapse" type="button" aria-label={collapsed ? text.expand : text.collapse} onClick={onCollapse}>
          {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
        </button>
      </div>

      <nav className="sidebar-primary" aria-label={text.navigation}>
        <NavLink className="sidebar-nav-link" to="/task" onClick={(event) => { if (!onNavigate()) event.preventDefault(); }}>
          <FilePlus2 size={19} aria-hidden="true" /> {!collapsed ? <span>{text.newTask}</span> : null}
        </NavLink>
        <NavLink className="sidebar-nav-link" to="/publications" onClick={(event) => { if (!onNavigate()) event.preventDefault(); }}>
          <Newspaper size={19} aria-hidden="true" /> {!collapsed ? <span>{text.publications}</span> : null}
        </NavLink>
      </nav>

      <section className="sidebar-tasks" aria-label={text.tasks}>
        {!collapsed ? (
          <button
            className="sidebar-section-toggle"
            type="button"
            aria-expanded={tasksOpen}
            onClick={() => {
              const next = !tasksOpen;
              setTasksOpen(next);
              window.localStorage.setItem("liyan.tasksOpen", String(next));
            }}
          >
            {text.tasks} {tasksOpen ? <ChevronLeft size={14} /> : <ChevronRight size={14} />}
          </button>
        ) : null}
        {tasksOpen || collapsed ? (
          <div className="sidebar-task-list">
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
              <LoadMoreTasks onVisible={onLoadMore} />
            ) : null}
            {!collapsed && tasks.length === 0 ? <p className="sidebar-empty">{text.empty}</p> : null}
          </div>
        ) : null}
      </section>

      <div className="sidebar-account">
        <button className="sidebar-account__action" type="button" onClick={onTheme}>
          {themeIcon} {!collapsed ? <span>{theme === "system" ? "System" : theme}</span> : null}
        </button>
        <button className="sidebar-account__action" type="button" onClick={onLocale}>
          <Languages size={18} /> {!collapsed ? <span>{text.language}</span> : null}
        </button>
        <div className="sidebar-identity">
          <span className="avatar" aria-hidden="true">{identity.email.charAt(0).toUpperCase()}</span>
          {!collapsed ? <span className="sidebar-identity__email">{identity.email}</span> : null}
        </div>
        <button className="sidebar-account__action" type="button" onClick={onSignOut}>
          <LogOut size={18} /> {!collapsed ? <span>{text.signOut}</span> : null}
        </button>
      </div>
    </aside>
  );
}

function TaskRoute({
  tasks,
  identity,
  accessToken,
  onDeleted,
  onSourceEditing,
}: {
  tasks: TaskSummary[];
  identity: Identity;
  accessToken: string;
  onDeleted(taskId: string): void;
  onSourceEditing(dirty: boolean): void;
}) {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const cached = tasks.find((candidate) => candidate.id === taskId);
  const taskQuery = useQuery({
    queryKey: ["task", accessToken, taskId],
    queryFn: () => getTask(accessToken, taskId!),
    enabled: Boolean(taskId && !cached),
  });
  const task = cached ?? taskQuery.data;
  if (!task) return <div className="route-empty"><h1>找不到这个任务</h1></div>;
  return (
    <TaskCard
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
  onSignOut,
}: {
  identity: Identity;
  accessToken: string;
  initialTasks: TaskSummary[];
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

  function setTasks(next: TaskSummary[]) {
    queryClient.setQueryData(["tasks", accessToken], {
      pages: [{ items: next, next_cursor: null }],
      pageParams: [null],
    });
  }

  function safeToNavigate() {
    if (!creationDirty && !sourceDirty) return true;
    return window.confirm("未保存的创建内容或来源修改会被丢弃，确定离开吗？");
  }

  function deleted(taskId: string) {
    setTasks(tasks.filter((task) => task.id !== taskId));
    if (currentTaskId === taskId) navigate("/task");
  }

  const sidebar = (
    <Sidebar
      identity={identity}
      accessToken={accessToken}
      tasks={tasks}
      collapsed={collapsed}
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
      onRenamed={(renamed) => setTasks([renamed, ...tasks.filter((task) => task.id !== renamed.id)])}
      onDeleted={deleted}
      onSignOut={() => { if (safeToNavigate()) void onSignOut(); }}
      onNavigate={() => {
        const allowed = safeToNavigate();
        if (allowed) setMobileOpen(false);
        return allowed;
      }}
      hasMore={taskQuery.hasNextPage}
      onLoadMore={() => void taskQuery.fetchNextPage()}
    />
  );

  return (
    <div className="app-frame" data-sidebar-collapsed={collapsed || undefined}>
      <div className="desktop-sidebar">{sidebar}</div>
      <Dialog.Root open={mobileOpen} onOpenChange={setMobileOpen}>
        <Dialog.Trigger className="mobile-menu-button" aria-label="打开导航">
          <Menu size={22} />
        </Dialog.Trigger>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="mobile-drawer">
            <Dialog.Title className="sr-only">主导航</Dialog.Title>
            <Dialog.Close className="icon-button mobile-drawer__close" aria-label="关闭导航"><X size={20} /></Dialog.Close>
            {sidebar}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <main className="route-surface">
        <Routes>
          <Route path="/" element={<Navigate to="/task" replace />} />
          <Route
            path="/task"
            element={
              <div className="creation-page">
                <header className="page-heading">
                  <p className="section-kicker">任务创建会话</p>
                  <h1>新建立言任务</h1>
                  <p>添加一至三个来源，确认后才会创建正式任务。</p>
                </header>
                <TaskCreationSession
                  accessToken={accessToken}
                  onDirtyChange={setCreationDirty}
                  onClose={() => undefined}
                  onCreated={(task) => {
                    setCreationDirty(false);
                    setTasks([task, ...tasks.filter((current) => current.id !== task.id)]);
                    navigate(`/task/${task.id}`);
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
              />
            }
          />
          <Route
            path="/publications"
            element={
              <PublicationCenter
                userId={identity.id}
                accessToken={accessToken}
                onClose={() => navigate("/task")}
                onOpenTask={(taskId) => navigate(`/task/${taskId}`)}
                initialTaskId={new URLSearchParams(location.search).get("taskId")}
                initialRevisionId={new URLSearchParams(location.search).get("revisionId")}
                onPublicationChanged={() => void taskQuery.refetch()}
              />
            }
          />
          <Route path="*" element={<Navigate to="/task" replace />} />
        </Routes>
      </main>
    </div>
  );
}
