import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicationCenter } from "./PublicationCenter";
import { articleContentHash } from "./articleContentHash";

const DRAFT = { title: "编辑中的标题", body_markdown: "还没保存的正文。" };

const eligible = {
  task_id: "task-1",
  task_number: 1,
  task_display_name: "四天工作制",
  task_version_id: "version-1",
  revision_id: "revision-2",
  revision_number: 2,
  title: "四天工作制的真问题",
  body_markdown: "工时只是生产方式的一部分。",
  content_hash: "saved-hash",
  saved_at: "2026-08-23T10:00:00Z",
};

const target = {
  key: "lsforum",
  platform: "lsforum_blog",
  display_name: "LSForum Blog",
  site_url: "https://lsforum.example",
  author: "Zeng Zong",
};

function respondWith() {
  type FetchCall = (request: Request) => Promise<Response>;
  const requests: Request[] = [];
  const fetchMock = vi.fn<FetchCall>(async (request) => {
    requests.push(request.clone());
    const path = new URL(request.url).pathname;
    if (path.endsWith("/publication/targets")) return Response.json({ items: [target] });
    if (path.endsWith("/publication/eligible-articles")) {
      return Response.json({ items: [eligible] });
    }
    if (request.method === "GET" && path.endsWith("/publication/publish-tasks")) {
      return Response.json({ items: [] });
    }
    return Response.json({ detail: "有未保存的修改，请先保存后再发布。" }, { status: 409 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("PublicationCenter", () => {
  it("sends the browser draft's own hash so unsaved edits cannot publish unnoticed", async () => {
    localStorage.setItem(
      "liyan:working-copy:v1:user-1:task-1",
      JSON.stringify(DRAFT),
    );
    const requests = respondWith();
    const user = userEvent.setup();
    render(
      <PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />,
    );

    await user.click(await screen.findByRole("button", { name: /四天工作制的真问题/ }));
    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Birdy Yao");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      revision_id: "revision-2",
      author: "Birdy Yao",
      working_copy_hash: await articleContentHash(DRAFT),
    });
    // The server's own reason, not a generic refusal: "unsaved edits",
    // "superseded Revision", and "already submitted" call for different acts.
    expect(
      await screen.findByText("有未保存的修改，请先保存后再发布。"),
    ).toBeInTheDocument();
  });

  it("vouches for the saved Revision when this browser holds no draft at all", async () => {
    const requests = respondWith();
    const user = userEvent.setup();
    render(
      <PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />,
    );

    await user.click(await screen.findByRole("button", { name: /四天工作制的真问题/ }));
    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Birdy Yao");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      working_copy_hash: "saved-hash",
    });
  });

  it("shows retained Preview evidence without needing the original task", async () => {
    vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path.endsWith("/publication/eligible-articles")) return Response.json({ items: [] });
      if (path.endsWith("/publication/publish-tasks")) {
        return Response.json({ items: [{
          id: "publish-1",
          status: "succeeded",
          task_id: "deleted-task",
          task_version_id: "version-1",
          revision_id: "revision-2",
          revision_number: 2,
          title: "仍可追溯的文章",
          body_markdown: "锁定正文",
          target,
          author: "Birdy Yao",
          post_type: "opinion",
          requested_status: "preview",
          preview_url: "https://lsforum.example/preview/kept",
          external_slug: "kept",
          external_version: "1",
          response_evidence: { previewPath: "/preview/kept" },
          failure_message: null,
          created_at: "2026-08-23T10:00:00Z",
          completed_at: "2026-08-23T10:01:00Z",
          execution: null,
        }] });
      }
      return new Response(null, { status: 404 });
    }));

    render(<PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />);

    expect(await screen.findByText("仍可追溯的文章")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开 Blog Preview" })).toHaveAttribute(
      "href",
      "https://lsforum.example/preview/kept",
    );
    expect(screen.getByText(/草稿 2/)).toBeInTheDocument();
  });

  const record = (status: string, overrides: Record<string, unknown> = {}) => ({
    id: "publish-1",
    status,
    task_id: "task-1",
    task_version_id: "version-1",
    revision_id: "revision-2",
    revision_number: 2,
    title: "四天工作制的真问题",
    body_markdown: "锁定正文",
    target,
    author: "Birdy Yao",
    post_type: "opinion",
    requested_status: "preview",
    preview_url: null,
    external_slug: null,
    external_version: null,
    response_evidence: null,
    failure_message: "Blog 暂时无法提交，请稍后重试。",
    created_at: "2026-08-23T10:00:00Z",
    completed_at: "2026-08-23T10:01:00Z",
    execution: null,
    attempts: [],
    ...overrides,
  });

  function listing(items: unknown[]) {
    const requests: Request[] = [];
    vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
      requests.push(request.clone());
      const path = new URL(request.url).pathname;
      if (path.endsWith("/publication/eligible-articles")) return Response.json({ items: [] });
      if (path.endsWith("/publication/targets")) return Response.json({ items: [target] });
      if (path.endsWith("/retry")) return Response.json(record("pending"));
      if (path.endsWith("/publication/publish-tasks")) return Response.json({ items });
      return new Response(null, { status: 404 });
    }));
    return requests;
  }

  it("keeps a definitive failure recoverable after the confirmation screen is gone", async () => {
    const requests = listing([record("failed")]);
    const user = userEvent.setup();

    render(<PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />);

    await user.click(await screen.findByRole("button", { name: "重试本次提交" }));

    const retried = requests.find((request) => request.url.endsWith("/retry"));
    expect(retried).toBeDefined();
    expect(retried!.method).toBe("POST");
  });

  it("warns before a retry resends behind a newer Revision, and keeps one key", async () => {
    const requests: Request[] = [];
    let retries = 0;
    vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
      requests.push(request.clone());
      const path = new URL(request.url).pathname;
      if (path.endsWith("/publication/eligible-articles")) return Response.json({ items: [] });
      if (path.endsWith("/publication/targets")) return Response.json({ items: [target] });
      if (path.endsWith("/retry")) {
        retries += 1;
        return retries === 1
          ? Response.json(
              { detail: "该立言任务已有文章提交到这个发布目标。继续发布会新建另一条 Blog 内容。" },
              { status: 412 },
            )
          : Response.json(record("pending"));
      }
      if (path.endsWith("/publication/publish-tasks")) {
        return Response.json({ items: [record("failed")] });
      }
      return new Response(null, { status: 404 });
    }));
    const user = userEvent.setup();

    render(<PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />);

    await user.click(await screen.findByRole("button", { name: "重试本次提交" }));
    expect(await screen.findByText(/继续发布会新建另一条 Blog 内容/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "仍要发布" }));

    const sent = requests.filter((request) => request.url.endsWith("/retry"));
    expect(sent).toHaveLength(2);
    const bodies = [JSON.parse(await sent[0].text()), JSON.parse(await sent[1].text())];
    expect(bodies[0].acknowledge_existing_preview).toBe(false);
    expect(bodies[1].acknowledge_existing_preview).toBe(true);
    // One retry, one key: the acknowledged resend is the same attempt, so the
    // server's repeated-key guard still recognises it as one.
    expect(bodies[1].idempotency_key).toBe(bodies[0].idempotency_key);
  });

  it("offers no resend for an outcome nobody can confirm", async () => {
    listing([record("outcome_unknown")]);

    render(<PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />);

    expect(await screen.findByText("四天工作制的真问题")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试本次提交" })).not.toBeInTheDocument();
  });
});
