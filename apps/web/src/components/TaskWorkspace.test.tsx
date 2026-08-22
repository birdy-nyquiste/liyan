import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskWorkspace } from "./TaskWorkspace";

const formalTask = {
  id: "task-1",
  number: 1,
  display_name: "First source",
  first_source_title: "First source",
  additional_source_count: 0,
  created_at: "2026-08-22T18:00:00Z",
  current_version_id: "version-1",
  current_version_number: 1,
};

describe("task creation session", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("previews normalized content and confirms a 立言任务", async () => {
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.url.endsWith("/task-creation/prepare")) {
        return Response.json({
          source: {
            title: "Useful source",
            body: "First line\n\nSecond line.",
            provenance: null,
          },
          warnings: [
            {
              code: "missing_provenance",
              message: "Provenance is missing; you can still create the task.",
            },
          ],
          can_confirm: true,
        });
      }
      if (request.url.endsWith("/task-creation/confirm")) {
        return Response.json({
          task: formalTask,
          source_revision: {
            id: "revision-1",
            title: "Useful source",
            body: "First line\n\nSecond line.",
            provenance: null,
          },
        });
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const onTaskCreated = vi.fn();
    const user = userEvent.setup();

    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[]}
        onTaskCreated={onTaskCreated}
        onSignOut={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.type(screen.getByLabelText("来源标题"), "  Useful   source  ");
    await user.type(screen.getByLabelText("来源正文"), " First line\n\nSecond line. ");
    await user.click(screen.getByRole("button", { name: "预览来源" }));

    expect(await screen.findByRole("heading", { name: "确认来源" })).toBeInTheDocument();
    expect(
      screen.getByText((_, element) =>
        element?.tagName === "PRE" && element.textContent === "First line\n\nSecond line.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("未填写出处，仍可继续创建。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "确认并创建任务" }));

    expect(onTaskCreated).toHaveBeenCalledWith(formalTask);
    const requests = fetch.mock.calls.map(([request]) => request as Request);
    expect(requests).toHaveLength(2);
    expect(requests[0]?.headers.get("Authorization")).toBe("Bearer access-token");
    const confirmation = JSON.parse(await requests[1]!.clone().text()) as {
      idempotency_key: string;
      source: { title: string };
    };
    expect(confirmation.idempotency_key).toBeTruthy();
    expect(confirmation.source.title).toBe("Useful source");
  });

  it("keeps prepared page state after confirmation fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(async (request: Request) => {
        if (request.url.endsWith("/task-creation/prepare")) {
          return Response.json({
            source: { title: "Source", body: "Body", provenance: null },
            warnings: [],
            can_confirm: true,
          });
        }
        return Response.json({ detail: "Temporary failure" }, { status: 503 });
      }),
    );
    const user = userEvent.setup();
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[]}
        onTaskCreated={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.type(screen.getByLabelText("来源标题"), "Source");
    await user.type(screen.getByLabelText("来源正文"), "Body");
    await user.click(screen.getByRole("button", { name: "预览来源" }));
    await user.click(await screen.findByRole("button", { name: "确认并创建任务" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("创建失败，内容仍保留在此页面。请重试。");
    expect(screen.getByRole("heading", { name: "确认来源" })).toBeInTheDocument();
    expect(screen.getByText("Body", { selector: "pre" })).toBeInTheDocument();
  });

  it("warns before leaving a dirty browser-local creation session", async () => {
    const user = userEvent.setup();
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[]}
        onTaskCreated={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.type(screen.getByLabelText("来源正文"), "Unsaved text");

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("shows per-来源 URL processing and editable extracted content", async () => {
    const execution = {
      id: "execution-1",
      operation: "fetch_url",
      status: "queued",
      attempt: 1,
      input_version: 1,
      trace_id: "trace-1",
      created_at: "2026-08-22T18:00:00Z",
      started_at: null,
      finished_at: null,
      cancellation_requested_at: null,
      result_id: null,
      error: null,
    };
    const processing = {
      id: "url-source-1",
      client_session_id: "session-1",
      client_source_id: "source-1",
      input_url: "https://example.com/article",
      normalized_url: "https://example.com/article",
      input_version: 1,
      status: "processing",
      title: null,
      body: null,
      provenance: null,
      warnings: [],
      failure: null,
      active_execution: execution,
      capabilities: { can_retry: false, can_replace: true, can_cancel: true },
    };
    const ready = {
      ...processing,
      status: "ready",
      title: "Extracted article",
      body: "Full extracted body.",
      provenance: "https://example.com/article",
      active_execution: {
        ...execution,
        status: "succeeded",
        result_id: "result-1",
        started_at: "2026-08-22T18:00:01Z",
        finished_at: "2026-08-22T18:00:02Z",
      },
      capabilities: { can_retry: false, can_replace: true, can_cancel: false },
    };
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "POST" && request.url.endsWith("/task-creation/url-sources")) {
        return Response.json(processing, { status: 201 });
      }
      if (request.method === "GET" && request.url.endsWith("/url-source-1")) {
        return Response.json(ready);
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[]}
        onTaskCreated={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.click(screen.getByRole("button", { name: "公共文章链接" }));
    await user.type(screen.getByLabelText("来源网址"), "https://example.com/article");
    await user.click(screen.getByRole("button", { name: "开始提取" }));

    expect(await screen.findByText("提取完成")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Extracted article")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Full extracted body.")).toBeInTheDocument();
    expect(screen.getByText("尝试 1 · 已完成")).toBeInTheDocument();
    const requests = fetch.mock.calls.map(([request]) => request as Request);
    expect(requests).toHaveLength(2);
    expect(requests.every((request) => request.headers.get("Authorization") === "Bearer access-token"))
      .toBe(true);
  });

  it("uploads a document and shows editable deterministic parse output", async () => {
    const execution = {
      id: "execution-file-1",
      operation: "parse_file",
      status: "queued",
      attempt: 1,
      input_version: 1,
      trace_id: "trace-file-1",
      created_at: "2026-08-22T18:00:00Z",
      started_at: null,
      finished_at: null,
      cancellation_requested_at: null,
      result_id: null,
      error: null,
    };
    const processing = {
      id: "file-source-1",
      client_session_id: "session-1",
      client_source_id: "source-1",
      filename: "brief.md",
      content_type: "text/markdown",
      content_hash: "abc123",
      size_bytes: 24,
      input_version: 1,
      status: "processing",
      title: null,
      body: null,
      provenance: null,
      warnings: [],
      failure: null,
      active_execution: execution,
      capabilities: { can_retry: false, can_replace: false, can_cancel: true },
    };
    const ready = {
      ...processing,
      status: "ready",
      title: "brief",
      body: "# Brief\n\nParsed content.",
      provenance: "brief.md",
      active_execution: {
        ...execution,
        status: "succeeded",
        result_id: "result-file-1",
        started_at: "2026-08-22T18:00:01Z",
        finished_at: "2026-08-22T18:00:02Z",
      },
      capabilities: { can_retry: false, can_replace: true, can_cancel: false },
    };
    const fetch = vi.fn().mockImplementation(async (request: Request) => {
      if (request.method === "POST" && request.url.endsWith("/task-creation/file-sources")) {
        return Response.json(processing, { status: 201 });
      }
      if (request.method === "GET" && request.url.endsWith("/file-source-1")) {
        return Response.json(ready);
      }
      return new Response(null, { status: 404 });
    });
    vi.stubGlobal("fetch", fetch);
    const user = userEvent.setup();
    render(
      <TaskWorkspace
        identity={{ id: "user-1", email: "writer@example.com" }}
        accessToken="access-token"
        tasks={[]}
        onTaskCreated={vi.fn()}
        onSignOut={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "新建立言任务" }));
    await user.click(screen.getByRole("button", { name: "上传文件" }));
    await user.upload(
      screen.getByLabelText("来源文件"),
      new File(["# Brief\n\nParsed content."], "brief.md", { type: "text/markdown" }),
    );
    await user.click(screen.getByRole("button", { name: "开始解析" }));

    expect(await screen.findByText("解析完成")).toBeInTheDocument();
    expect(screen.getByDisplayValue("brief")).toBeInTheDocument();
    expect(document.getElementById("file-source-body")).toHaveValue(
      "# Brief\n\nParsed content.",
    );
    expect(screen.getByText("brief.md · 24 字节")).toBeInTheDocument();
    const uploadRequest = fetch.mock.calls[0]?.[0] as Request;
    expect(uploadRequest.headers.get("Authorization")).toBe("Bearer access-token");
    expect(uploadRequest.headers.get("Content-Type")).toMatch(/^multipart\/form-data; boundary=/);
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

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("First source", { selector: ".task-card__source" })).toBeInTheDocument();
    expect(
      screen.getByText((_, element) =>
        element?.tagName === "P" && element.textContent?.startsWith("另有 0 个来源") === true,
      ),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "重命名 First source" }));
    const input = screen.getByLabelText("任务名称");
    await user.clear(input);
    await user.type(input, "Renamed");
    await user.click(screen.getByRole("button", { name: "保存名称" }));

    expect(await screen.findByRole("heading", { name: "Renamed" })).toBeInTheDocument();
    expect(screen.getByText("First source", { selector: ".task-card__source" })).toBeInTheDocument();
  });
});
