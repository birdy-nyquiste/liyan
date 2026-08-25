import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicationConfirmation, type PublicationArticle } from "./PublicationConfirmation";

const ARTICLE: PublicationArticle = {
  taskId: "task-1",
  taskLabel: "四天工作制",
  revisionId: "revision-2",
  revisionNumber: 2,
  title: "四天工作制的真问题",
  bodyMarkdown: "工时只是生产方式的一部分。",
};

const target = (key: string, displayName: string) => ({
  key,
  platform: "lsforum_blog",
  display_name: displayName,
  site_url: `https://${key}.example`,
});

function publishTask(status: string, previewUrl: string | null = null) {
  return {
    id: "publish-1",
    status,
    task_id: "task-1",
    task_version_id: "version-1",
    revision_id: "revision-2",
    revision_number: 2,
    title: ARTICLE.title,
    body_markdown: ARTICLE.bodyMarkdown,
    target: target("lsforum", "LSForum Blog"),
    author: "Zeng Zong",
    post_type: "opinion",
    requested_status: "preview",
    preview_url: previewUrl,
    external_slug: null,
    external_version: null,
    response_evidence: null,
    failure_message: status === "failed" ? "Blog 没有返回可用的 Preview，请稍后重试。" : null,
    created_at: "2026-08-23T10:00:00Z",
    completed_at: null,
    execution: null,
  };
}

/** A refusal the component must read, rather than a payload it can use. */
const refusal = (status: number, detail: string) => ({ __status: status, detail });

/** Answers each request by URL so the order of the component's reads is free. */
function respondWith(routes: Array<[RegExp, unknown | unknown[]]>) {
  type FetchCall = (request: Request) => Promise<Response>;
  const requests: Request[] = [];
  const fetchMock = vi.fn<FetchCall>(async (request) => {
    requests.push(request.clone());
    for (const [pattern, payload] of routes) {
      if (!pattern.test(new URL(request.url).pathname)) continue;
      const answer = Array.isArray(payload)
        ? (payload.length > 1 ? payload.shift() : payload[0])
        : payload;
      const refused = answer as { __status?: number };
      return Response.json(answer, { status: refused?.__status ?? 200 });
    }
    throw new Error(`No route for ${request.url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("PublicationConfirmation", () => {
  it("preselects a sole authorized target and submits the locked snapshot", async () => {
    const requests = respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [/\/publication\/publish-tasks\//, publishTask("succeeded", "https://lsforum.example/preview/abc")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        workingCopyHash="hash-2"
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    expect(await screen.findByText("LSForum Blog（https://lsforum.example）")).toBeInTheDocument();
    expect(screen.queryByLabelText("发布目标")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      task_id: "task-1",
      revision_id: "revision-2",
      target_key: "lsforum",
      author: "Zeng Zong",
      working_copy_hash: "hash-2",
    });
  });

  it("reports a pending publication so task deletion capability can refresh", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
    ]);
    const onStatusChange = vi.fn();
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        onStatusChange={onStatusChange}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    expect(onStatusChange).toHaveBeenCalledOnce();
  });

  it("asks which destination to use when more than one is authorized", async () => {
    respondWith([
      [
        /\/publication\/targets$/,
        {
          items: [
            target("lsforum", "LSForum Blog"),
            target("lsforum-cn", "LSForum 中文站"),
          ],
        },
      ],
    ]);
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        onClose={() => undefined}
      />,
    );

    expect(await screen.findByLabelText("发布目标")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
  });

  it("shows the Preview URL as the terminal outcome and claims nothing beyond it", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [
        /\/publication\/publish-tasks\//,
        publishTask("succeeded", "https://lsforum.example/preview/abc"),
      ],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const link = await screen.findByRole("link", { name: "https://lsforum.example/preview/abc" });
    expect(link).toHaveAttribute("href", "https://lsforum.example/preview/abc");
    expect(screen.getByText(/是否在 Blog 上公开发布，由你在 Blog 决定/)).toBeInTheDocument();
    expect(screen.queryByText(/受密码保护/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认发布" })).not.toBeInTheDocument();
  });

  it("never offers a resend once a submission's outcome is unknown", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [/\/publication\/publish-tasks\//, publishTask("outcome_unknown")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    expect(await screen.findByText("本次提交结果未知。")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "确认发布" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /重试|重新/ })).not.toBeInTheDocument();
  });

  it("resends the original submission when Blog definitively refused it", async () => {
    const requests = respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [/\/publication\/publish-tasks\/[^/]+\/retry$/, publishTask("pending")],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [
        /\/publication\/publish-tasks\//,
        [publishTask("failed"), publishTask("succeeded", "https://lsforum.example/preview/abc")],
      ],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    await user.click(await screen.findByRole("button", { name: "重试本次提交" }));

    const retried = requests.find((request) => request.url.includes("/retry"));
    expect(retried).toBeDefined();
    expect(retried!.method).toBe("POST");
    // The retry carries no content: the snapshot is already the server's, and
    // a body naming a title or Revision could smuggle in something newer.
    expect(JSON.parse(await retried!.text())).toEqual({
      idempotency_key: expect.any(String),
      acknowledge_existing_preview: false,
    });
    expect(
      await screen.findByRole("link", { name: "https://lsforum.example/preview/abc" }),
    ).toBeInTheDocument();
  });

  it("warns before a retry resends behind a newer Revision", async () => {
    const requests = respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [
        /\/publication\/publish-tasks\/[^/]+\/retry$/,
        [
          refusal(412, "该立言任务已有文章提交到这个发布目标。继续发布会新建另一条 Blog 内容。"),
          publishTask("pending"),
        ],
      ],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [/\/publication\/publish-tasks\//, publishTask("failed")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));
    await user.click(await screen.findByRole("button", { name: "重试本次提交" }));

    expect(await screen.findByText(/继续发布会新建另一条 Blog 内容/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "仍要发布" }));

    const retries = requests.filter((request) => request.url.includes("/retry"));
    expect(retries).toHaveLength(2);
    expect(JSON.parse(await retries[0].text())).toMatchObject({
      acknowledge_existing_preview: false,
    });
    expect(JSON.parse(await retries[1].text())).toMatchObject({
      acknowledge_existing_preview: true,
    });
  });

  it("warns that a newer Revision creates another Blog item before it does", async () => {
    const requests = respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
      [
        /\/publication\/publish-tasks$/,
        [
          refusal(412, "该立言任务已有文章提交到这个发布目标。继续发布会新建另一条 Blog 内容。"),
          publishTask("pending"),
        ],
      ],
      [/\/publication\/publish-tasks\//, publishTask("pending")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    expect(await screen.findByText(/继续发布会新建另一条 Blog 内容/)).toBeInTheDocument();
    const posts = requests.filter((request) => request.method === "POST");
    expect(posts).toHaveLength(1);
    expect(JSON.parse(await posts[0].text())).toMatchObject({
      acknowledge_existing_preview: false,
    });

    await user.click(screen.getByRole("button", { name: "仍要发布" }));

    const acknowledged = requests.filter((request) => request.method === "POST");
    expect(acknowledged).toHaveLength(2);
    expect(JSON.parse(await acknowledged[1].text())).toMatchObject({
      acknowledge_existing_preview: true,
    });
  });

  it("lets the author be typed while the article itself stays read-only", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
    ]);
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        onClose={() => undefined}
      />,
    );

    expect(
      await screen.findByText("确认页只能预览。要修改标题或正文，请返回编辑并保存新草稿。"),
    ).toBeInTheDocument();
    // The author is the only thing this screen may change.
    expect(screen.getAllByRole("textbox")).toHaveLength(1);
    expect(screen.getByLabelText("作者（显示在 Blog 上）")).toBeInTheDocument();
    expect(screen.queryByDisplayValue(ARTICLE.title)).not.toBeInTheDocument();
  });

  it("will not confirm until an author has been named", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        onClose={() => undefined}
      />,
    );

    expect(await screen.findByRole("button", { name: "确认发布" })).toBeDisabled();
    await user.type(screen.getByLabelText("作者（显示在 Blog 上）"), "  ");
    expect(screen.getByRole("button", { name: "确认发布" })).toBeDisabled();
    await user.type(screen.getByLabelText("作者（显示在 Blog 上）"), "Zeng Zong");
    expect(screen.getByRole("button", { name: "确认发布" })).toBeEnabled();
  });

  it("offers the name this browser published under last time", async () => {
    localStorage.setItem("liyan:publication-author:v1:user-1", "Birdy Yao");
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog")] }],
    ]);
    render(
      <PublicationConfirmation
        userId="user-1"
        accessToken="token"
        article={ARTICLE}
        onClose={() => undefined}
      />,
    );

    expect(await screen.findByDisplayValue("Birdy Yao")).toBeInTheDocument();
  });
});
