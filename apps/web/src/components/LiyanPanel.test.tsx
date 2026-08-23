import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiyanPanel } from "./LiyanPanel";

function execution(status = "running") {
  return {
    id: "liyan-execution-1",
    operation: "generate_article",
    status,
    attempt: 1,
    input_version: 1,
    trace_id: "trace-1",
    created_at: "2026-08-22T18:00:00Z",
    started_at: "2026-08-22T18:00:01Z",
    finished_at: status === "running" ? null : "2026-08-22T18:00:04Z",
    cancellation_requested_at: null,
    result_id: status === "succeeded" ? "result-1" : null,
    error: null,
  };
}

function state(status: "absent" | "running" | "succeeded" | "failed" = "absent") {
  const active = status === "running";
  return {
    task_id: "task-1",
    task_version_id: "version-1",
    status,
    execution: status === "absent" ? null : execution(status),
    result: status === "succeeded" ? {
      id: "result-1",
      execution_id: "liyan-execution-1",
      task_version_id: "version-1",
      title: "完整文章",
      body_markdown: "第一段。\n\n## 继续讨论\n\n第二段。",
      instruction: "语气克制。",
      prompt_version: "liyan-v0.1",
      model: "deepseek-v4-flash",
      created_at: "2026-08-22T18:00:04Z",
    } : null,
    capabilities: {
      can_generate: !active,
      can_cancel: active,
      retry: { allowed: true, remaining: 2, allowed_at: null },
      unavailable_reason: active ? "立言文章正在生成中。" : null,
    },
  };
}

function respondWith(...payloads: unknown[]) {
  type FetchCall = (request: Request) => Promise<Response>;
  const fetchMock = vi.fn<FetchCall>(async () => {
    const payload = payloads.length > 1 ? payloads.shift() : payloads[0];
    return Response.json(payload);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("LiyanPanel", () => {
  it("generates from the optional instruction and initializes an unsaved Working Copy", async () => {
    const fetchMock = respondWith(state(), state("running"), state("running"), state("succeeded"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" pollIntervalMs={1} />);

    await user.type(await screen.findByLabelText("立言指令（可选）"), "语气克制。");
    await user.click(screen.getByRole("button", { name: "生成立言" }));

    expect(await screen.findByDisplayValue("完整文章")).toBeInTheDocument();
    expect(screen.getByText("未保存 Working Copy")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([request]) => request.method === "POST");
    expect(post).toBeDefined();
    const body = JSON.parse(await post![0].clone().text()) as { instruction: string };
    expect(body.instruction).toBe("语气克制。");
  });

  it("offers a completed background result after navigation before loading it locally", async () => {
    respondWith(state("succeeded"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    expect(await screen.findByText("有一份已完成的立言结果可载入。")) .toBeInTheDocument();
    expect(screen.queryByText("未保存 Working Copy")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "载入为未保存草稿" }));

    expect(screen.getByText("未保存 Working Copy")).toBeInTheDocument();
    expect(screen.getByDisplayValue("完整文章")).toBeInTheDocument();
  });

  it("projects canonical Markdown through the constrained Tiptap editor", async () => {
    respondWith(state("succeeded"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));

    expect(screen.getByRole("heading", { name: "继续讨论", level: 2 })).toBeInTheDocument();
    expect(screen.getByRole("toolbar", { name: "文章格式" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "加粗" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "分隔线" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "文章正文" }).querySelector("pre")).toBeNull();
  });

  it("replaces an existing Working Copy with the completed regeneration", async () => {
    const initial = state("succeeded");
    const running = {
      ...state("running"),
      execution: { ...execution("running"), id: "liyan-execution-2" },
    };
    const replacement = {
      ...state("succeeded"),
      execution: {
        ...execution("succeeded"),
        id: "liyan-execution-2",
        result_id: "result-2",
      },
      result: {
        ...state("succeeded").result!,
        id: "result-2",
        execution_id: "liyan-execution-2",
        title: "替代文章",
        body_markdown: "这是完整的新正文。",
      },
    };
    respondWith(initial, running, running, replacement);
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" pollIntervalMs={1} />);

    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));
    expect(screen.getByDisplayValue("完整文章")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "生成立言" }));

    expect(await screen.findByDisplayValue("替代文章")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("完整文章")).not.toBeInTheDocument();
  });

  it("terminates the active Execution advertised by the server", async () => {
    const cancelled = {
      ...state("failed"),
      status: "cancelled",
      execution: { ...execution("cancelled"), error: { code: "cancelled", message: "立言生成已取消，可重新发起。" } },
    };
    const fetchMock = respondWith(state("running"), { ...execution("running"), status: "cancel_requested" }, cancelled);
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" pollIntervalMs={5000} />);

    await user.click(await screen.findByRole("button", { name: "终止生成" }));

    await waitFor(() => expect(screen.getByText("立言生成已取消，可重新发起。")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([request]) => request.url.includes("/executions/liyan-execution-1/cancel"))).toBe(true);
  });

  it("reuses the same idempotency key when the start response is lost", async () => {
    let starts = 0;
    const fetchMock = vi.fn(async (request: Request) => {
      if (request.method === "POST" && request.url.endsWith("/liyan-runs")) {
        starts += 1;
        if (starts === 1) throw new TypeError("connection lost");
        return Response.json(state("running"));
      }
      return Response.json(state());
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    const generate = await screen.findByRole("button", { name: "生成立言" });
    await user.click(generate);
    await waitFor(() => expect(starts).toBe(1));
    await user.click(generate);

    const posts = fetchMock.mock.calls.filter(([request]) => request.method === "POST");
    expect(posts).toHaveLength(2);
    const first = JSON.parse(await posts[0]![0].clone().text()) as { idempotency_key: string };
    const second = JSON.parse(await posts[1]![0].clone().text()) as { idempotency_key: string };
    expect(second.idempotency_key).toBe(first.idempotency_key);
  });

  it("applies a completed result returned directly by the start replay", async () => {
    respondWith(state(), state("succeeded"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    await user.click(await screen.findByRole("button", { name: "生成立言" }));

    expect(await screen.findByDisplayValue("完整文章")).toBeInTheDocument();
    expect(screen.getByText("未保存 Working Copy")).toBeInTheDocument();
    expect(screen.queryByText("有一份已完成的立言结果可载入。")).not.toBeInTheDocument();
  });

  it("edits the Tiptap Working Copy and sends the canonical Markdown on regeneration", async () => {
    const fetchMock = respondWith(state("succeeded"), state("running"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));
    const title = screen.getByRole("textbox", { name: "文章标题" });
    const body = screen.getByRole("textbox", { name: "文章正文" });
    await user.clear(title);
    await user.type(title, "手动标题");
    await user.clear(body);
    await user.type(body, "Edited body.");
    await user.click(screen.getByRole("button", { name: "生成立言" }));

    const post = fetchMock.mock.calls.find(([request]) => request.method === "POST");
    expect(fetchMock.mock.calls.filter(([request]) => request.method === "POST")).toHaveLength(1);
    expect(post![0].url).toContain("/liyan-runs");
    const request = JSON.parse(await post![0].clone().text()) as {
      working_copy: { title: string; body_markdown: string };
    };
    expect(request.working_copy).toEqual({
      title: "手动标题",
      body_markdown: "Edited body.",
    });
  });

  it("regenerates from the sanitized canonical form of an untouched Agent result", async () => {
    const resultWithUnsupportedMarkdown = {
      ...state("succeeded"),
      result: {
        ...state("succeeded").result!,
        body_markdown: "<p>保留正文</p>\n\n![配图](https://example.com/a.png)",
      },
    };
    const fetchMock = respondWith(resultWithUnsupportedMarkdown, state("running"));
    const user = userEvent.setup();
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));
    expect(screen.getByRole("textbox", { name: "文章正文" })).toHaveTextContent("保留正文配图");
    await user.click(screen.getByRole("button", { name: "生成立言" }));

    const post = fetchMock.mock.calls.find(([request]) => request.method === "POST");
    const request = JSON.parse(await post![0].clone().text()) as {
      working_copy: { body_markdown: string };
    };
    expect(request.working_copy.body_markdown).toBe("保留正文\n\n配图");
  });

  it("recovers a Working Copy after refresh in the same browser", async () => {
    respondWith(state("succeeded"));
    const user = userEvent.setup();
    const first = render(
      <LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />,
    );

    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));
    await user.clear(screen.getByRole("textbox", { name: "文章标题" }));
    await user.type(screen.getByRole("textbox", { name: "文章标题" }), "浏览器恢复标题");
    await user.clear(screen.getByRole("textbox", { name: "文章正文" }));
    await user.type(screen.getByRole("textbox", { name: "文章正文" }), "Recovered body.");
    first.unmount();
    respondWith(state("succeeded"));
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />);

    expect(await screen.findByDisplayValue("浏览器恢复标题")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "文章正文" })).toHaveTextContent("Recovered body.");
    expect(screen.queryByText("有一份已完成的立言结果可载入。")).not.toBeInTheDocument();
    expect(screen.getByText("仅保存在当前浏览器；退出登录、换设备或清除浏览器数据后无法恢复。")).toBeInTheDocument();
  });

  it("isolates browser-local Working Copies by authenticated user and task", async () => {
    respondWith(state("succeeded"));
    const user = userEvent.setup();
    const first = render(
      <LiyanPanel userId="user-1" accessToken="token" taskId="task-1" />,
    );
    await user.click(await screen.findByRole("button", { name: "载入为未保存草稿" }));
    await user.clear(screen.getByRole("textbox", { name: "文章标题" }));
    await user.type(screen.getByRole("textbox", { name: "文章标题" }), "用户一的内容");
    first.unmount();

    respondWith(state("succeeded"));
    const second = render(
      <LiyanPanel userId="user-2" accessToken="token" taskId="task-1" />,
    );
    expect(await screen.findByText("有一份已完成的立言结果可载入。")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("用户一的内容")).not.toBeInTheDocument();
    second.unmount();

    respondWith(state("succeeded"));
    render(<LiyanPanel userId="user-1" accessToken="token" taskId="task-2" />);
    expect(await screen.findByText("有一份已完成的立言结果可载入。")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("用户一的内容")).not.toBeInTheDocument();
  });
});
