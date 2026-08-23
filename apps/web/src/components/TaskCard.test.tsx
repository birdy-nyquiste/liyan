import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TaskCard } from "./TaskCard";

const task = {
  id: "task-1",
  number: 1,
  display_name: "Test Header",
  first_source_title: "Test Header",
  additional_source_count: 0,
  created_at: "2026-08-23T16:52:00Z",
  current_version_id: "version-1",
  current_version_number: 1,
};

const versionSnapshot = {
  id: "version-1",
  number: 1,
  created_at: "2026-08-23T16:52:00Z",
  is_current: true,
  sources: [
    {
      source_id: "source-1",
      id: "revision-1",
      title: "Test Header",
      body: "Test main.",
      provenance: "Birdy",
    },
  ],
  capabilities: { can_edit: true, can_restore: false, unavailable_reason: null },
};

const zhiyanOverview = {
  task_id: "task-1",
  task_version_id: "version-1",
  task_version_number: 1,
  sources: [
    {
      source_revision_id: "revision-1",
      title: "Test Header",
      status: "succeeded",
      execution: null,
      report: {
        id: "report-1",
        created_at: "2026-08-23T16:53:42Z",
        document: {
          overview: {
            content_summary: "极简占位文本。",
            fact_check_summary: "未执行外部核查。",
            reading_note: "视为格式性记录。",
            key_findings: [],
          },
          source: { genre: "测试", provenance: "Birdy", completeness: "极不完整", note: null },
          facts: { items: [], empty_state: "没有可核查对象。" },
          viewpoints: { items: [], empty_state: "没有观点表达。" },
          logic: { argument_chain: null, items: [], empty_state: "没有论证结构。" },
          intent: {
            explicit_purpose: null,
            items: [],
            target_audience: null,
            expression_methods: [],
            empty_state: "没有意图信号。",
          },
          evidence: { items: [], empty_state: "未引用外部资料。" },
        },
      },
      capabilities: {
        can_start: false,
        can_cancel: false,
        retry: { allowed: false, remaining: 0, allowed_at: null },
        unavailable_reason: null,
      },
    },
  ],
  liyan: { can_generate: true, unavailable_reason: null },
};

const liyanState = {
  task_id: "task-1",
  task_version_id: "version-1",
  status: "absent",
  execution: null,
  result: null,
  request: null,
  revisions: { current: null, historical: [], historical_limit: 3 },
  capabilities: {
    can_generate: true,
    can_cancel: false,
    can_save: true,
    publishable_revision_id: null,
    publication_unavailable_reason: "保存文章后才能发布。",
    retry: { allowed: true, remaining: 2, allowed_at: null },
    unavailable_reason: null,
  },
};

/**
 * Routes by URL and delays the version list past everything else, which is the
 * order the real server answers in and the order that used to strand 立言.
 */
function respondWithVersionListLast() {
  const counts = { versions: 0, zhiyan: 0, liyan: 0 };
  const fetchMock = vi.fn(async (request: Request) => {
    const url = request.url;
    if (url.includes("/versions/") && url.endsWith("/zhiyan")) {
      counts.zhiyan += 1;
      return Response.json(zhiyanOverview);
    }
    if (url.endsWith("/versions")) {
      counts.versions += 1;
      await new Promise((resolve) => setTimeout(resolve, 20));
      return Response.json({ items: [versionSnapshot], historical_limit: 3 });
    }
    if (url.endsWith("/liyan")) {
      counts.liyan += 1;
      return Response.json(liyanState);
    }
    return Response.json({});
  });
  vi.stubGlobal("fetch", fetchMock);
  return counts;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("TaskCard", () => {
  it("opens 立言 once every report has succeeded, whatever order the reads settle in", async () => {
    respondWithVersionListLast();

    render(
      <TaskCard task={task} userId="user-1" accessToken="token" opened />,
    );

    // 立言 must still be open once every read has settled, not merely flash open
    // before the version list arrives and resets it.
    await screen.findByRole("button", { name: "生成立言" });
    await new Promise((resolve) => setTimeout(resolve, 150));

    expect(screen.getByRole("button", { name: "生成立言" })).toBeInTheDocument();
    expect(screen.queryByText("全部知言报告已完成，可以进入立言。")).not.toBeInTheDocument();
  });

  it("settles without refetching the same reads on every render", async () => {
    const counts = respondWithVersionListLast();

    render(
      <TaskCard task={task} userId="user-1" accessToken="token" opened />,
    );
    await screen.findByRole("button", { name: "生成立言" });
    await new Promise((resolve) => setTimeout(resolve, 120));

    expect(counts.versions).toBeLessThanOrEqual(2);
    expect(counts.zhiyan).toBeLessThanOrEqual(2);
  });

  it("keeps 立言 shut while a report is still unfinished", async () => {
    const running = {
      ...zhiyanOverview,
      sources: [{ ...zhiyanOverview.sources[0], status: "running", report: null }],
      liyan: { can_generate: false, unavailable_reason: "全部知言报告成功后才能生成立言。" },
    };
    vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
      if (request.url.includes("/versions/") && request.url.endsWith("/zhiyan")) {
        return Response.json(running);
      }
      if (request.url.endsWith("/versions")) {
        return Response.json({ items: [versionSnapshot], historical_limit: 3 });
      }
      return Response.json(liyanState);
    }));

    render(
      <TaskCard task={task} userId="user-1" accessToken="token" opened />,
    );

    // The reason shown is the server's, never one the workbench invented.
    await waitFor(() =>
      expect(screen.getByText("全部知言报告成功后才能生成立言。")).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "生成立言" })).not.toBeInTheDocument();
  });

  it("moves focus to 立言 once the server permits generating it", async () => {
    respondWithVersionListLast();

    render(<TaskCard task={task} userId="user-1" accessToken="token" opened />);

    const heading = await screen.findByRole("heading", { name: "立言文章" });
    await waitFor(() => expect(heading).toHaveFocus());
  });

  it("folds 来源 away during normal work and opens it for editing", async () => {
    respondWithVersionListLast();
    const user = userEvent.setup();

    render(<TaskCard task={task} userId="user-1" accessToken="token" opened />);
    await screen.findByRole("button", { name: "生成立言" });

    const sources = screen.getByRole("button", { name: /来源/ });
    expect(sources).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("1 个来源 · V1")).toBeInTheDocument();

    await user.click(sources);

    expect(sources).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /^知言/ })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "生成立言" })).not.toBeInTheDocument();
  });

  it("states how many reports are done in the 知言 area summary", async () => {
    respondWithVersionListLast();

    render(<TaskCard task={task} userId="user-1" accessToken="token" opened />);

    expect(await screen.findByText("1 份报告已完成")).toBeInTheDocument();
  });
});
