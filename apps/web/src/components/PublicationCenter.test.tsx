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

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Birdy Yao");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      revision_id: "revision-2",
      author: "Birdy Yao",
      working_copy_hash: await articleContentHash(DRAFT),
    });
    expect(
      await screen.findByText("该文章已不可发布，请保存最新 Revision 后重试。"),
    ).toBeInTheDocument();
  });

  it("vouches for the saved Revision when this browser holds no draft at all", async () => {
    const requests = respondWith();
    const user = userEvent.setup();
    render(
      <PublicationCenter userId="user-1" accessToken="token" onClose={() => undefined} />,
    );

    await user.click(await screen.findByRole("button", { name: "发布" }));
    await user.type(await screen.findByLabelText("作者（显示在 Blog 上）"), "Birdy Yao");
    await user.click(screen.getByRole("button", { name: "确认发布" }));

    const posted = requests.find((request) => request.method === "POST");
    expect(JSON.parse(await posted!.text())).toMatchObject({
      working_copy_hash: "saved-hash",
    });
  });
});
