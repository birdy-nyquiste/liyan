import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@workbench/api/client";
import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";

import { Basket } from "./Basket";

const createUrlSource = vi.hoisted(() => vi.fn());
const deleteTaskCreationSource = vi.hoisted(() => vi.fn());
const getTaskCreationSession = vi.hoisted(() => vi.fn());

vi.mock("@workbench/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@workbench/api/client")>()),
  createUrlSource,
  deleteTaskCreationSource,
  getTaskCreationSession,
}));

type SourceOverrides = {
  id?: string;
  status?: "processing" | "ready" | "warning" | "failure";
  title?: string | null;
  body?: string | null;
  provenance?: string | null;
  warnings?: { code: string; message: string }[];
  failure?: { code: string; message: string } | null;
};

function source(overrides: SourceOverrides = {}) {
  return {
    id: overrides.id ?? "source-1",
    client_source_id: "client-1",
    kind: "url" as const,
    input_version: 1,
    status: overrides.status ?? "ready",
    title: overrides.title === undefined ? "那件事到底是怎么发生的" : overrides.title,
    body: overrides.body === undefined ? "x".repeat(4182) : overrides.body,
    provenance:
      overrides.provenance === undefined
        ? "https://www.example-news.com/analysis"
        : overrides.provenance,
    warnings: overrides.warnings ?? [],
    failure: overrides.failure ?? null,
    active_execution: null,
    capabilities: { can_retry: true, can_replace: true, can_cancel: false, can_edit: true },
  };
}

function session(sources: ReturnType<typeof source>[], overrides: Record<string, unknown> = {}) {
  const allSettled = sources.every((one) => one.status === "ready" || one.status === "warning");
  return {
    client_session_id: "a-basket",
    source_count: sources.length,
    max_sources: 3 as const,
    can_add: sources.length < 3,
    can_confirm: sources.length > 0 && allSettled,
    confirmation_disabled_reason: null,
    sources,
    ...overrides,
  };
}

/** `chrome.tabs`, answering with whatever page the test says the user is on. */
function onPage(url: string, title = "那件事到底是怎么发生的") {
  vi.stubGlobal("chrome", {
    tabs: { query: vi.fn(async () => [{ url, title }]) },
  });
}

function renderBasket() {
  return render(
    <InterfaceLocaleProvider locale="zh">
      <Basket accessToken="a-token" basketId="a-basket" />
    </InterfaceLocaleProvider>,
  );
}

beforeEach(() => {
  createUrlSource.mockReset();
  deleteTaskCreationSource.mockReset();
  getTaskCreationSession.mockReset();
  onPage("https://www.example-news.com/analysis");
});

describe("an empty basket", () => {
  it("says so, and cannot be confirmed", async () => {
    getTaskCreationSession.mockResolvedValue(session([]));
    renderBasket();

    expect(await screen.findByText(/还没有来源/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认创建任务" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "添加当前页面" })).toBeEnabled();
  });
});

describe("添加当前页面", () => {
  it("submits the tab's address and shows what came back", async () => {
    const user = userEvent.setup();
    getTaskCreationSession.mockResolvedValueOnce(session([]));
    createUrlSource.mockResolvedValue(source({ status: "processing" }));
    getTaskCreationSession.mockResolvedValue(session([source()]));
    renderBasket();

    await user.click(await screen.findByRole("button", { name: "添加当前页面" }));

    expect(await screen.findByText("那件事到底是怎么发生的")).toBeInTheDocument();
    expect(createUrlSource).toHaveBeenCalledWith(
      "a-token",
      "a-basket",
      expect.any(String),
      "https://www.example-news.com/analysis",
    );
  });

  /**
   * The refusal for 额度不足 and for the per-user ceiling is written for a user
   * and is the only thing that explains the button having done nothing.
   */
  it("shows the server's own refusal", async () => {
    const user = userEvent.setup();
    getTaskCreationSession.mockResolvedValue(session([]));
    createUrlSource.mockRejectedValue(new ApiError(402, "额度不足，购买后可继续。"));
    renderBasket();

    await user.click(await screen.findByRole("button", { name: "添加当前页面" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("额度不足，购买后可继续。");
  });
});

describe("when the page cannot be added", () => {
  it("is dead on a page 立言阁 could never fetch, and says why", async () => {
    onPage("chrome://settings", "设置");
    getTaskCreationSession.mockResolvedValue(session([]));
    renderBasket();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "添加当前页面" })).toBeDisabled(),
    );
    expect(screen.getByText(/不是公开网址/)).toBeInTheDocument();
  });

  /**
   * `provenance` is the server's normalized URL, not what the tab said, so the
   * two are compared in that form — otherwise a trailing slash would let the
   * same page in twice.
   */
  it("is dead when this page is already in the basket, however it is spelled", async () => {
    onPage("https://WWW.Example-News.com/analysis#section-2");
    getTaskCreationSession.mockResolvedValue(
      session([source({ provenance: "https://www.example-news.com/analysis" })]),
    );
    renderBasket();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "添加当前页面" })).toBeDisabled(),
    );
    expect(screen.getByText("这一页已经在来源里了。")).toBeInTheDocument();
  });

  it("is dead at three, and says a source must go first", async () => {
    getTaskCreationSession.mockResolvedValue(
      session([
        source({ id: "a", provenance: "https://a.example.com/one" }),
        source({ id: "b", provenance: "https://b.example.com/two" }),
        source({ id: "c", provenance: "https://c.example.com/three" }),
      ]),
    );
    renderBasket();

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "添加当前页面" })).toBeDisabled(),
    );
    expect(screen.getByText(/已达三条上限/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "确认创建任务（3 条来源）" })).toBeEnabled();
  });
});

describe("a source that failed", () => {
  /**
   * Confirmation demands every 来源 in the session be ready and takes no
   * subset, so one failure stops the whole basket. The server's own reason for
   * that says "wait", which is wrong here: a failure never becomes ready.
   */
  it("blocks the basket, and is told to be removed rather than waited for", async () => {
    getTaskCreationSession.mockResolvedValue(
      session([
        source({ id: "a" }),
        source({
          id: "b",
          status: "failure",
          title: null,
          body: null,
          provenance: "https://paywalled.example.com/piece",
          failure: { code: "fetch_failed", message: "无法读取正文，可能需要登录后才能访问。" },
        }),
      ]),
    );
    renderBasket();

    expect(await screen.findByText(/移除抓取失败的来源/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认创建任务/ })).toBeDisabled();
    expect(screen.getByText("无法读取正文，可能需要登录后才能访问。")).toBeInTheDocument();
    expect(screen.getByText(/未消耗额度/)).toBeInTheDocument();
  });

  it("goes when its × is pressed", async () => {
    const user = userEvent.setup();
    const failed = source({
      id: "b",
      status: "failure",
      title: null,
      provenance: "https://paywalled.example.com/piece",
      failure: { code: "fetch_failed", message: "无法读取正文。" },
    });
    getTaskCreationSession.mockResolvedValueOnce(session([source({ id: "a" }), failed]));
    deleteTaskCreationSource.mockResolvedValue(undefined);
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    renderBasket();

    await user.click(await screen.findByRole("button", { name: /移除 paywalled/ }));

    await waitFor(() => expect(deleteTaskCreationSource).toHaveBeenCalledWith("a-token", "b"));
    expect(await screen.findByRole("button", { name: "确认创建任务（1 条来源）" })).toBeEnabled();
  });
});

describe("a source still being fetched", () => {
  it("keeps asking until it settles, and then stops", async () => {
    vi.useFakeTimers();
    try {
      getTaskCreationSession.mockResolvedValueOnce(
        session([source({ status: "processing", title: null, body: null, provenance: null })]),
      );
      getTaskCreationSession.mockResolvedValue(session([source()]));
      renderBasket();

      await vi.waitFor(() => expect(screen.getByText("处理中")).toBeInTheDocument());
      await vi.advanceTimersByTimeAsync(2000);
      await vi.waitFor(() => expect(screen.getByText(/4182 字/)).toBeInTheDocument());

      const asked = getTaskCreationSession.mock.calls.length;
      await vi.advanceTimersByTimeAsync(5000);
      expect(getTaskCreationSession.mock.calls.length).toBe(asked);
    } finally {
      vi.useRealTimers();
    }
  });
});
