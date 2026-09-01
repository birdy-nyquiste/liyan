import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@workbench/api/client";
import { InterfaceLocaleProvider } from "@workbench/interfaceLocale";

import { Basket } from "./Basket";

const confirmTaskCreationSession = vi.hoisted(() => vi.fn());
const createUrlSource = vi.hoisted(() => vi.fn());
const deleteTaskCreationSource = vi.hoisted(() => vi.fn());
const getTaskCreationSession = vi.hoisted(() => vi.fn());

vi.mock("@workbench/api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@workbench/api/client")>()),
  confirmTaskCreationSession,
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

/** `chrome`, answering with whatever page the test says the user is on. */
let browser: { kept: Map<string, unknown> };

function onPage(url: string, title = "那件事到底是怎么发生的") {
  const kept = new Map<string, unknown>([["liyan.creation-session", "a-basket"]]);
  browser = { kept };
  vi.stubGlobal("chrome", {
    tabs: { query: vi.fn(async () => [{ url, title }]) },
    storage: {
      local: {
        get: async (key: string) =>
          kept.has(key) ? { [key]: kept.get(key) } : ({} as Record<string, unknown>),
        set: async (entries: Record<string, unknown>) => {
          for (const [key, value] of Object.entries(entries)) kept.set(key, value);
        },
        remove: async (key: string) => {
          kept.delete(key);
        },
      },
    },
  });
}

const onCreated = vi.fn();
const onCollected = vi.fn();

function renderBasket(recovered = false) {
  return render(
    <InterfaceLocaleProvider locale="zh">
      <Basket
        accessToken="a-token"
        basketId="a-basket"
        recovered={recovered}
        onCreated={onCreated}
        onCollected={onCollected}
      />
    </InterfaceLocaleProvider>,
  );
}

beforeEach(() => {
  confirmTaskCreationSession.mockReset();
  onCreated.mockReset();
  onCollected.mockReset();
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
          failure: { code: "fetch_failed", message: "The article could not be fetched." },
        }),
      ]),
    );
    renderBasket();

    expect(await screen.findByText(/移除抓取失败的来源/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /确认创建任务/ })).toBeDisabled();
    // The row says it in 工作台's words for `fetch_failed`, not the server's.
    expect(screen.getByText("文章抓取失败，请重试或替换来源。")).toBeInTheDocument();
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

describe("确认创建任务", () => {
  /**
   * The whole basket goes at once, warnings accepted in the same request. A
   * separate confirmation for the warning would be a second click for
   * something the user has already been shown, directly above the button.
   */
  it("sends every source, and accepts the warnings on the way", async () => {
    const user = userEvent.setup();
    const thin = source({
      id: "b",
      status: "warning",
      title: "简讯",
      body: "x".repeat(214),
      provenance: "https://wire.example.net/brief",
      warnings: [{ code: "short_body", message: "正文较短。" }],
    });
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" }), thin]));
    confirmTaskCreationSession.mockResolvedValue({ id: "task-1", display_name: "那件事" });
    renderBasket();

    await user.click(await screen.findByRole("button", { name: /确认创建任务/ }));

    await waitFor(() =>
      expect(confirmTaskCreationSession).toHaveBeenCalledWith(
        "a-token",
        expect.any(String),
        "a-basket",
        ["a", "b"],
        { b: 1 },
      ),
    );
    expect(onCreated).toHaveBeenCalledWith({ id: "task-1", display_name: "那件事" });
  });

  /**
   * The key is per basket, not per attempt: a confirmation whose answer the
   * panel never saw is repeated, and the server hands back the task it already
   * made rather than making a second one.
   */
  it("confirms twice under one key", async () => {
    const user = userEvent.setup();
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    confirmTaskCreationSession.mockRejectedValueOnce(new ApiError(503));
    confirmTaskCreationSession.mockResolvedValue({ id: "task-1", display_name: "那件事" });
    renderBasket();

    await user.click(await screen.findByRole("button", { name: /确认创建任务/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("创建任务失败，请重试。");

    await user.click(screen.getByRole("button", { name: /确认创建任务/ }));
    await waitFor(() => expect(onCreated).toHaveBeenCalled());

    const [first, second] = confirmTaskCreationSession.mock.calls;
    expect(second[1]).toBe(first[1]);
  });

  /** The basket is let go only once the task exists. */
  it("keeps the basket when confirmation fails", async () => {
    const user = userEvent.setup();
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    confirmTaskCreationSession.mockRejectedValue(new ApiError(402, "额度不足，购买后可继续。"));
    renderBasket();

    await user.click(await screen.findByRole("button", { name: /确认创建任务/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("额度不足，购买后可继续。");
    expect(onCreated).not.toHaveBeenCalled();
    expect(browser.kept.get("liyan.creation-session")).toBe("a-basket");
  });
});

describe("a basket found in storage", () => {
  it("says it is the one left unfinished", async () => {
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    renderBasket(true);

    expect(await screen.findByText("上次还有一个没建完的任务。")).toBeInTheDocument();
  });

  /**
   * Cleanup takes an unconfirmed 来源 on its own clock, and the panel is shut
   * while it happens. Telling the user their basket expired would name
   * something they cannot act on; 主屏 is somewhere that works.
   */
  it("goes quietly back to 主屏 when the server has nothing left of it", async () => {
    getTaskCreationSession.mockResolvedValue(session([]));
    renderBasket(true);

    await waitFor(() => expect(onCollected).toHaveBeenCalled());
    expect(browser.kept.has("liyan.creation-session")).toBe(false);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  /** A basket opened a second ago is also empty, and has not expired. */
  it("leaves a basket just opened alone", async () => {
    getTaskCreationSession.mockResolvedValue(session([]));
    renderBasket(false);

    expect(await screen.findByText(/还没有来源/)).toBeInTheDocument();
    expect(onCollected).not.toHaveBeenCalled();
    expect(browser.kept.get("liyan.creation-session")).toBe("a-basket");
  });

  it("shows how old a source is once that is what matters", async () => {
    const twoHoursAgo = Date.now() - 2 * 60 * 60 * 1000;
    browser.kept.set(
      "liyan.creation-added",
      JSON.stringify({ a: { at: twoHoursAgo, url: "https://www.example-news.com/analysis" } }),
    );
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    renderBasket(true);

    expect(await screen.findByText("2 小时前")).toBeInTheDocument();
  });

  it("warns before the oldest source is collected", async () => {
    const nearlyADayAgo = Date.now() - 21 * 60 * 60 * 1000;
    browser.kept.set(
      "liyan.creation-added",
      JSON.stringify({ a: { at: nearlyADayAgo, url: "https://www.example-news.com/analysis" } }),
    );
    getTaskCreationSession.mockResolvedValue(session([source({ id: "a" })]));
    renderBasket(true);

    expect(await screen.findByText(/小时后被清理/)).toBeInTheDocument();
  });
});

describe("a 来源 the server has no address for", () => {
  /**
   * `provenance` exists only once a fetch has succeeded. A failed row would
   * otherwise be nameless — and which page failed is the only thing the person
   * looking at it needs to know.
   */
  it("is named by the address the panel submitted", async () => {
    browser.kept.set(
      "liyan.creation-added",
      JSON.stringify({ b: { at: Date.now(), url: "https://paywalled.example.com/the-piece" } }),
    );
    getTaskCreationSession.mockResolvedValue(
      session([
        source({
          id: "b",
          status: "failure",
          title: null,
          body: null,
          provenance: null,
          failure: {
            code: "inaccessible_url",
            message: "The article is not publicly accessible. Replace this source or try another URL.",
          },
        }),
      ]),
    );
    renderBasket(true);

    expect(await screen.findByText("paywalled.example.com/the-piece")).toBeInTheDocument();
  });

  /**
   * The server's failure text is written for whoever reads the logs. 工作台
   * already owns a sentence per code for the person looking at the screen.
   */
  it("says why in the workbench's own words, not the server's", async () => {
    getTaskCreationSession.mockResolvedValue(
      session([
        source({
          id: "b",
          status: "failure",
          title: null,
          body: null,
          provenance: null,
          failure: {
            code: "inaccessible_url",
            message: "The article is not publicly accessible. Replace this source or try another URL.",
          },
        }),
      ]),
    );
    renderBasket(true);

    expect(
      await screen.findByText("该文章无法公开访问，请替换来源或尝试其他网址。"),
    ).toBeInTheDocument();
  });

  /** A warning is named by what it is, not by the commonest one. */
  it("names a missing title as a missing title", async () => {
    getTaskCreationSession.mockResolvedValue(
      session([
        source({
          id: "a",
          status: "warning",
          title: "www.rfc-editor.org",
          body: "x".repeat(23302),
          warnings: [
            { code: "missing_title", message: "No page title was found; review the suggested title." },
          ],
        }),
      ]),
    );
    renderBasket(true);

    expect(await screen.findByText("缺少标题 · 23302 字")).toBeInTheDocument();
  });

  /**
   * While a fetch is running the server has no provenance to compare against,
   * so without what the panel submitted the same page could go in twice.
   */
  it("still knows this page is in the basket while its fetch is running", async () => {
    browser.kept.set(
      "liyan.creation-added",
      JSON.stringify({ a: { at: Date.now(), url: "https://www.example-news.com/analysis" } }),
    );
    getTaskCreationSession.mockResolvedValue(
      session([source({ id: "a", status: "processing", title: null, body: null, provenance: null })]),
    );
    renderBasket(true);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "添加当前页面" })).toBeDisabled(),
    );
    expect(screen.getByText("这一页已经在来源里了。")).toBeInTheDocument();
  });
});
