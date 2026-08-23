import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskWorkspace } from "./TaskWorkspace";
import type { TaskSummary } from "../auth/state";

const formalTask = {
  id: "task-1",
  number: 1,
  display_name: "First source",
  first_source_title: "First source",
  additional_source_count: 0,
  created_at: "2026-08-22T18:00:00Z",
  current_version_id: "version-1",
  current_version_number: 1,
  can_delete: true,
  delete_disabled_reason: null,
};

type TestSource = {
  id: string;
  client_source_id: string;
  kind: "pasted" | "url" | "file";
  input_version: number;
  status: "ready" | "warning";
  title: string;
  body: string;
  provenance: string | null;
  warnings: { code: string; message: string }[];
  failure: null;
  active_execution: null;
  capabilities: {
    can_retry: boolean;
    can_replace: boolean;
    can_edit: boolean;
    can_delete: boolean;
    can_cancel: boolean;
  };
};

const capabilities = {
  can_retry: false,
  can_replace: true,
  can_edit: true,
  can_delete: true,
  can_cancel: false,
};

function sessionResponse(sources: TestSource[]) {
  return {
    client_session_id: "browser-session",
    source_count: sources.length,
    max_sources: 3,
    can_add: sources.length < 3,
    can_confirm: sources.length > 0,
    confirmation_disabled_reason: sources.length ? null : "Add at least one source.",
    sources,
  };
}

function renderWorkspace(onTaskCreated = vi.fn()) {
  function StatefulWorkspace() {
    const [tasks, setTasks] = useState<TaskSummary[]>([]);
    return (
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={tasks}
        onTaskCreated={(task) => {
          setTasks((current) => [task, ...current]);
          onTaskCreated(task);
        }}
        onSignOut={vi.fn()}
      />
    );
  }
  render(<StatefulWorkspace />);
  return onTaskCreated;
}

describe("task creation session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
  });

  it("retains three mixed sources and confirms their accepted snapshot in order", async () => {
    const sources: TestSource[] = [];
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "GET" && request.url.includes("/task-creation/sessions/")) {
        return Response.json(sessionResponse(sources));
      }
      if (request.method === "POST" && request.url.endsWith("/task-creation/pasted-sources")) {
        const source: TestSource = {
          id: "pasted-1",
          client_source_id: "client-pasted",
          kind: "pasted",
          input_version: 1,
          status: "warning",
          title: "Pasted source",
          body: "Pasted body.",
          provenance: null,
          warnings: [{ code: "missing_provenance", message: "Missing provenance." }],
          failure: null,
          active_execution: null,
          capabilities,
        };
        sources.push(source);
        return Response.json(source, { status: 201 });
      }
      if (request.method === "POST" && request.url.endsWith("/task-creation/url-sources")) {
        const source: TestSource = {
          id: "url-1",
          client_source_id: "client-url",
          kind: "url",
          input_version: 1,
          status: "ready",
          title: "Fetched article",
          body: "Fetched body.",
          provenance: "https://example.com/article",
          warnings: [],
          failure: null,
          active_execution: null,
          capabilities,
        };
        sources.push(source);
        return Response.json(source, { status: 201 });
      }
      if (request.method === "POST" && request.url.endsWith("/task-creation/file-sources")) {
        const source: TestSource = {
          id: "file-1",
          client_source_id: "client-file",
          kind: "file",
          input_version: 1,
          status: "ready",
          title: "brief",
          body: "Parsed file body.",
          provenance: "brief.md",
          warnings: [],
          failure: null,
          active_execution: null,
          capabilities,
        };
        sources.push(source);
        return Response.json(source, { status: 201 });
      }
      if (request.method === "PATCH" && request.url.endsWith("/task-creation/pasted-sources/pasted-1")) {
        const updated = JSON.parse(await request.clone().text()) as {
          title: string;
          body: string;
          provenance: string | null;
        };
        Object.assign(sources[0]!, updated, { input_version: 2 });
        return Response.json(sources[0]);
      }
      if (request.method === "POST" && request.url.endsWith("/task-creation/confirm")) {
        return Response.json({
          task: { ...formalTask, additional_source_count: 2 },
          source_revision: { id: "revision-1", title: "Pasted source", body: "Pasted body.", provenance: null },
          source_revisions: [],
        });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const onTaskCreated = renderWorkspace();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await screen.findByText("请先添加来源。");
    await user.type(screen.getByLabelText("来源标题"), "Pasted source");
    await user.type(screen.getByLabelText("来源正文"), "Pasted body.");
    await user.click(screen.getByRole("button", { name: "添加来源" }));

    expect(await screen.findByText("粘贴文本 · Pasted source")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认并创建任务" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "公共文章链接" }));
    await user.type(screen.getByLabelText("来源网址"), "https://example.com/article");
    await user.click(screen.getByRole("button", { name: "添加来源" }));
    expect(await screen.findByText("公共文章链接 · Fetched article")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.upload(
      screen.getByLabelText("来源文件"),
      new File(["Parsed file body."], "brief.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "添加来源" }));
    expect(await screen.findByText("上传文件 · brief")).toBeInTheDocument();
    expect(screen.getByText("已达到三个来源上限；删除一个来源后可继续添加。")).toBeInTheDocument();

    const warningCheckbox = screen.getByRole("checkbox", { name: "我已检查并接受此来源的警告" });
    await user.click(warningCheckbox);
    const pastedCard = screen.getByText("粘贴文本 · Pasted source").closest("article");
    expect(pastedCard).not.toBeNull();
    const pastedTitle = within(pastedCard!).getByDisplayValue("Pasted source");
    await user.clear(pastedTitle);
    await user.type(pastedTitle, "Edited pasted source");
    expect(screen.getByRole("button", { name: "确认并创建任务" })).toBeDisabled();
    expect(screen.getByText("请先保存所有来源编辑。")).toBeInTheDocument();
    await user.click(within(pastedCard!).getByRole("button", { name: "保存此来源" }));
    expect(await screen.findByText("粘贴文本 · Edited pasted source")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "我已检查并接受此来源的警告" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "我已检查并接受此来源的警告" }));
    await user.click(screen.getByRole("button", { name: "确认并创建任务" }));

    expect(onTaskCreated).toHaveBeenCalledWith({ ...formalTask, additional_source_count: 2 });
    expect(screen.getByRole("article", { name: "已打开任务 First source" })).toHaveFocus();
    const confirmationRequest = fetch.mock.calls
      .map(([request]) => request as Request)
      .find((request) => request.url.endsWith("/task-creation/confirm"));
    expect(confirmationRequest?.headers.get("Authorization")).toBe("Bearer access-token");
    const confirmation = JSON.parse(await confirmationRequest!.clone().text()) as {
      source_ids: string[];
      accepted_warning_versions: Record<string, number>;
    };
    expect(confirmation.source_ids).toEqual(["pasted-1", "url-1", "file-1"]);
    expect(confirmation.accepted_warning_versions).toEqual({ "pasted-1": 2 });
  });

  it("keeps every retained source after confirmation fails", async () => {
    const retained: TestSource = {
      id: "pasted-1",
      client_source_id: "client-pasted",
      kind: "pasted",
      input_version: 1,
      status: "ready",
      title: "Retained source",
      body: "Retained body.",
      provenance: "Notes",
      warnings: [],
      failure: null,
      active_execution: null,
      capabilities,
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "GET") return Response.json(sessionResponse([retained]));
      return Response.json({ detail: "Temporary failure" }, { status: 503 });
    }));
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.click(await screen.findByRole("button", { name: "确认并创建任务" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建失败，来源仍保留在此会话中。请重试。");
    expect(screen.getByText("粘贴文本 · Retained source")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Retained body.")).toBeInTheDocument();
  });

  it("warns before leaving a dirty creation session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(sessionResponse([]))));
    const user = userEvent.setup();
    renderWorkspace();
    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.type(screen.getByLabelText("来源正文"), "Unsaved text");

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});

describe("立言任务 list", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows recognition fields and renames without changing source recognition", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...formalTask, display_name: "Renamed" })));
    const user = userEvent.setup();
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[formalTask]}
        onTaskCreated={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );

    const taskCard = screen.getByRole("article");
    expect(within(taskCard).getByText("#1")).toBeInTheDocument();
    expect(within(taskCard).getByText("First source", { selector: ".task-card__source" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重命名 First source" }));
    const input = screen.getByLabelText("任务名称");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.click(screen.getByRole("button", { name: "保存名称" }));

    expect(await screen.findByRole("heading", { name: "Renamed" })).toBeInTheDocument();
    expect(screen.getByText("First source", { selector: ".task-card__source" })).toBeInTheDocument();
  });

  it("requires confirmation and removes a deliberately deleted task", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();

    function DeletableWorkspace() {
      const [tasks, setTasks] = useState<TaskSummary[]>([formalTask]);
      return (
        <TaskWorkspace
          identity={{ id: "user-1", email: "writer@example.com" }}
          accessToken="access-token"
          tasks={tasks}
          onTaskCreated={vi.fn()}
          onTaskDeleted={(taskId) => setTasks((items) => items.filter((item) => item.id !== taskId))}
          onSignOut={vi.fn()}
        />
      );
    }
    render(<DeletableWorkspace />);

    await user.click(screen.getByRole("button", { name: "删除 First source" }));

    expect(confirm).toHaveBeenCalledWith("删除任务后将立即消失且无法恢复，确定删除吗？");
    expect(fetch).toHaveBeenCalledOnce();
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("DELETE");
    expect(JSON.parse(await request.text())).toEqual({ confirmed: true });
    expect(await screen.findByText("还没有立言任务")).toBeInTheDocument();
  });

  it("explains why a task with an unfinished publication cannot be deleted", () => {
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[{
          ...formalTask,
          can_delete: false,
          delete_disabled_reason: "关联的发布任务仍在执行，结束后才能删除立言任务。",
        }]}
        onTaskCreated={vi.fn()}
        onTaskDeleted={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "删除 First source" })).toBeDisabled();
    expect(screen.getByText("关联的发布任务仍在执行，结束后才能删除立言任务。")).toBeInTheDocument();
  });
});
