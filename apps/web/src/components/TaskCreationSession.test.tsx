import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskCreationSession } from "./TaskCreationSession";

const formalTask = {
  id: "task-1",
  number: 1,
  display_name: "First source",
  first_source_title: "First source",
  additional_source_count: 0,
  created_at: "2026-08-22T18:00:00Z",
  last_activity_at: "2026-08-22T18:00:00Z",
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
  status: "processing" | "ready" | "warning" | "failure";
  title: string;
  body: string;
  provenance: string | null;
  warnings: { code: string; message: string }[];
  failure: { code: string; message: string } | null;
  active_execution: { id: string; status: string } | null;
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

/**
 * The creation session is what these tests are about; the route that hosts it
 * hands it an access token and takes the finished task back.
 *
 * It also asks the account which 来源 kinds are the user's to submit, so it now
 * needs the query client and the router the workbench gives it. Retries are off
 * because a stubbed fetch that answers once should not be asked again while a
 * test waits.
 */
/**
 * The account, as a 付费用户 sees it. URL and file 来源 are theirs to submit, so
 * a suite that submits them has to say so — the tabs are locked until the
 * server confirms otherwise, deliberately, so that a slow answer never briefly
 * offers a 来源 kind the server is about to refuse.
 */
const PAYING_ACCOUNT = { remaining_credits: 100_000, is_paying_user: true };

function accountAnswer(request: Request): Response | null {
  return request.url.endsWith("/account") ? Response.json(PAYING_ACCOUNT) : null;
}

function renderSession(onCreated = vi.fn()) {
  const queries = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queries}>
      <MemoryRouter>
        <TaskCreationSession
          accessToken="access-token"
          onCreated={onCreated}
          onDirtyChange={vi.fn()}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onCreated;
}

describe("task creation session", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.sessionStorage.clear();
    // The creation session id now outlives a reload, so it must not outlive a test.
    window.localStorage.clear();
  });

  it("reveals theme only after sources and preserves it when returning", async () => {
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
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) =>
      accountAnswer(request) ?? Response.json(sessionResponse([retained]))));
    const user = userEvent.setup();

    renderSession();

    expect(await screen.findByRole("button", { name: "下一步：确定主题" })).toBeEnabled();
    expect(screen.queryByRole("textbox", { name: "主题" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一步：确定主题" }));
    await user.type(screen.getByRole("textbox", { name: "主题" }), "保留的主题");
    await user.click(screen.getByRole("button", { name: "返回来源" }));
    expect(screen.queryByRole("textbox", { name: "主题" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一步：确定主题" }));
    expect(screen.getByRole("textbox", { name: "主题" })).toHaveValue("保留的主题");
  });

  it("retains three mixed sources and confirms their accepted snapshot in order", async () => {
    const sources: TestSource[] = [];
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      const account = accountAnswer(request);
      if (account) return account;
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
    const onCreated = renderSession();
    const user = userEvent.setup();

    await screen.findByText("请先添加来源。");
    await user.click(screen.getByRole("button", { name: "添加来源" }));
    await user.type(screen.getByLabelText("来源标题"), "Pasted source");
    await user.type(screen.getByLabelText("来源正文"), "Pasted body.");
    await user.click(screen.getByRole("button", { name: "添加来源" }));

    expect(await screen.findByText("粘贴文本 · Pasted source")).toBeInTheDocument();
    // A warning no longer holds the task back; it is shown on the source itself.
    expect(screen.getByText("缺少出处信息；仍可继续创建任务。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一步：确定主题" })).toBeEnabled();
    expect(screen.queryByRole("textbox", { name: "主题" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "添加来源" }));
    await user.click(screen.getByRole("button", { name: "公共文章链接" }));
    await user.type(screen.getByLabelText("来源网址"), "https://example.com/article");
    await user.click(screen.getByRole("button", { name: "添加来源" }));
    expect(await screen.findByText("公共文章链接 · Fetched article")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "添加来源" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.upload(
      screen.getByLabelText("来源文件"),
      new File(["Parsed file body."], "brief.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "添加来源" }));
    expect(await screen.findByText("上传文件 · brief")).toBeInTheDocument();
    expect(screen.getByText("已达到三个来源上限；删除一个来源后可继续添加。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "编辑来源 Pasted source" }));
    const pastedCard = screen.getByText("粘贴文本 · Pasted source").closest("article");
    expect(pastedCard).not.toBeNull();
    const pastedTitle = within(pastedCard!).getByDisplayValue("Pasted source");
    await user.clear(pastedTitle);
    await user.type(pastedTitle, "Edited pasted source");
    // Leaving the field is what commits it; there is no save button to press.
    await user.tab();
    expect(await screen.findByText("粘贴文本 · Edited pasted source")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "下一步：确定主题" }));
    expect(screen.getByRole("textbox", { name: "主题" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "创建任务" }));

    expect(onCreated).toHaveBeenCalledWith({ ...formalTask, additional_source_count: 2 });
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

  it("says a source is being read while it is being prepared", async () => {
    const preparing: TestSource = {
      id: "url-1",
      client_source_id: "client-url",
      kind: "url",
      input_version: 1,
      status: "processing" as TestSource["status"],
      title: "Fetching article",
      body: "",
      provenance: "https://example.com/article",
      warnings: [],
      failure: null,
      active_execution: null,
      capabilities,
    };
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) =>
      accountAnswer(request) ?? Response.json(sessionResponse([preparing]))));

    renderSession();

    expect(await screen.findByRole("status")).toHaveTextContent("正在处理来源…");
  });

  it("leaves no processing dead end after a source is cancelled", async () => {
    const processing: TestSource = {
      id: "file-1",
      client_source_id: "client-file",
      kind: "file",
      input_version: 1,
      status: "processing",
      title: "report.pdf",
      body: "",
      provenance: "report.pdf",
      warnings: [],
      failure: null,
      active_execution: { id: "execution-1", status: "running" },
      capabilities: {
        can_retry: false,
        can_replace: false,
        can_edit: false,
        can_delete: false,
        can_cancel: true,
      },
    };
    const cancelled: TestSource = {
      ...processing,
      status: "failure",
      failure: { code: "cancelled", message: "Parsing was cancelled. Retry it or replace this source." },
      active_execution: { id: "execution-1", status: "cancelled" },
      capabilities: {
        can_retry: true,
        can_replace: true,
        can_edit: false,
        can_delete: true,
        can_cancel: false,
      },
    };
    let source = processing;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) => {
      const account = accountAnswer(request);
      if (account) return account;
      if (request.method === "GET") return Response.json(sessionResponse([source]));
      if (request.method === "POST" && request.url.endsWith("/executions/execution-1/cancel")) {
        source = cancelled;
        return Response.json(cancelled.active_execution, { status: 202 });
      }
      return new Response(null, { status: 404 });
    }));
    const user = userEvent.setup();

    renderSession();
    await user.click(await screen.findByRole("button", { name: "编辑来源 report.pdf" }));
    await user.click(screen.getByRole("button", { name: "取消处理" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("处理已取消，请重试或替换来源。");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "取消处理" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "删除来源" })).toBeEnabled();
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
      const account = accountAnswer(request);
      if (account) return account;
      if (request.method === "GET") return Response.json(sessionResponse([retained]));
      return Response.json({ detail: "Temporary failure" }, { status: 503 });
    }));
    const user = userEvent.setup();
    renderSession();
    await user.click(await screen.findByRole("button", { name: "下一步：确定主题" }));
    await user.click(await screen.findByRole("button", { name: "创建任务" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建失败，来源仍保留在此会话中。请重试。");
    await user.click(screen.getByRole("button", { name: "返回来源" }));
    expect(screen.getByText("粘贴文本 · Retained source")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "编辑来源 Retained source" }));
    expect(screen.getByDisplayValue("Retained body.")).toBeInTheDocument();
  });

  it("returns to the same creation session after a reload", async () => {
    const sources: TestSource[] = [];
    const requestedSessions: string[] = [];
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) => {
      const account = accountAnswer(request);
      if (account) return account;
      if (request.method === "GET") {
        requestedSessions.push(request.url.split("/").pop()!);
        return Response.json(sessionResponse(sources));
      }
      return new Response(null, { status: 404 });
    }));

    renderSession();
    await screen.findByText("请先添加来源。");
    cleanup();

    // A reload must reach the sources already added, not strand them in a
    // session nothing can name any more.
    renderSession();
    await screen.findByText("请先添加来源。");

    expect(new Set(requestedSessions).size).toBe(1);
  });

  it("warns before leaving a dirty creation session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (request: Request) =>
      accountAnswer(request) ?? Response.json(sessionResponse([]))));
    const user = userEvent.setup();
    renderSession();
    await user.click(await screen.findByRole("button", { name: "添加来源" }));
    await user.type(screen.getByLabelText("来源正文"), "Unsaved text");

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });
});
