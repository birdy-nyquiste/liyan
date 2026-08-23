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

const target = (key: string, displayName: string, author: string) => ({
  key,
  platform: "lsforum_blog",
  display_name: displayName,
  site_url: `https://${key}.example`,
  author,
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
    target: target("lsforum", "LSForum Blog", "Zeng Zong"),
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
      return Response.json(answer);
    }
    throw new Error(`No route for ${request.url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PublicationConfirmation", () => {
  it("preselects a sole authorized target and submits the locked snapshot", async () => {
    const requests = respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog", "Zeng Zong")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [/\/publication\/publish-tasks\//, publishTask("succeeded", "https://lsforum.example/preview/abc")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        accessToken="token"
        article={ARTICLE}
        workingCopyHash="hash-2"
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    expect(await screen.findByText("LSForum Blog（https://lsforum.example）")).toBeInTheDocument();
    expect(screen.getByText("Zeng Zong")).toBeInTheDocument();
    expect(screen.queryByLabelText("发布目标")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      task_id: "task-1",
      revision_id: "revision-2",
      target_key: "lsforum",
      working_copy_hash: "hash-2",
    });
  });

  it("asks which destination to use when more than one is authorized", async () => {
    respondWith([
      [
        /\/publication\/targets$/,
        {
          items: [
            target("lsforum", "LSForum Blog", "Zeng Zong"),
            target("lsforum-cn", "LSForum 中文站", "曾总"),
          ],
        },
      ],
    ]);
    render(
      <PublicationConfirmation
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
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog", "Zeng Zong")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [
        /\/publication\/publish-tasks\//,
        publishTask("succeeded", "https://lsforum.example/preview/abc"),
      ],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "确认发布" }));

    const link = await screen.findByRole("link", { name: "https://lsforum.example/preview/abc" });
    expect(link).toHaveAttribute("href", "https://lsforum.example/preview/abc");
    expect(screen.getByText(/是否在 Blog 上公开发布，由你在 Blog 决定/)).toBeInTheDocument();
    expect(screen.queryByText(/受密码保护/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "确认发布" })).not.toBeInTheDocument();
  });

  it("never offers a resend once a submission's outcome is unknown", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog", "Zeng Zong")] }],
      [/\/publication\/publish-tasks$/, publishTask("pending")],
      [/\/publication\/publish-tasks\//, publishTask("outcome_unknown")],
    ]);
    const user = userEvent.setup();
    render(
      <PublicationConfirmation
        accessToken="token"
        article={ARTICLE}
        pollIntervalMs={1}
        onClose={() => undefined}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "确认发布" }));

    expect(await screen.findByText("本次提交结果未知。")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "确认发布" })).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: /重试|重新/ })).not.toBeInTheDocument();
  });

  it("offers no confirmation at all when the article cannot be edited here", async () => {
    respondWith([
      [/\/publication\/targets$/, { items: [target("lsforum", "LSForum Blog", "Zeng Zong")] }],
    ]);
    render(
      <PublicationConfirmation
        accessToken="token"
        article={ARTICLE}
        onClose={() => undefined}
      />,
    );

    expect(
      await screen.findByText("确认页只能预览。要修改标题或正文，请返回编辑并保存新的 Revision。"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
});
