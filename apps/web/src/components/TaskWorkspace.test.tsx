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
    expect(screen.getByText("Body")).toBeInTheDocument();
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
