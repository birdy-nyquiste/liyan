import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemeReportView, type ThemeReportDocument } from "./ThemeReportView";
import { TaskZhiyanArea } from "./TaskZhiyanArea";
import { ThemeChoice } from "./ThemeChoice";

function themeDocument(): ThemeReportDocument {
  return {
    overview: {
      landscape: "公共讨论集中在生产率与人力成本两条线上。",
      consensus_and_dispute: "试验存在积极信号是共识，能否推广是争议。",
      key_findings: [{ ref_id: "TF-01", text: "试验样本以白领企业为主。" }],
      reading_note: "三个来源都把「试验成功」当作既定前提。",
    },
    facts: {
      items: [
        {
          id: "TF-01",
          claim: "参与试验的企业以知识工作为主。",
          relevance: "决定试验结论能覆盖哪些行业。",
          evidence_ids: ["TE-01"],
        },
      ],
      empty_state: null,
    },
    viewpoints: {
      items: [
        {
          id: "TV-01",
          position: "缩短工时会提高单位时间产出。",
          holders: "部分劳动经济学者。",
          grounds: "以试验期内营收指标为依据。",
          evidence_ids: [],
        },
      ],
      empty_state: null,
    },
    disagreements: {
      items: [
        {
          id: "TD-01",
          axis: "结论能否外推到连续生产行业。",
          sides: "支持方引用自愿参与企业的数据，反对方指出班次制约。",
          crux: "分歧取决于事实差异：样本行业构成不同。",
          evidence_ids: [],
        },
      ],
      empty_state: null,
    },
    blind_spots: {
      items: [
        {
          id: "TB-01",
          angle: "班次制行业的排班成本。",
          source_gap: "三个来源均未提及连续生产行业的排班安排。",
          why_it_matters: "这是政策能否推行的主要约束。",
          evidence_ids: ["TE-01"],
        },
      ],
      empty_state: null,
    },
    evidence: {
      items: [
        {
          id: "TE-01",
          title: "OECD: Working time and productivity",
          url: "https://oecd.org/four-day-week-evidence",
          explanation: "给出参与企业的行业构成。",
        },
      ],
      empty_state: null,
    },
  };
}

function themeState(overrides: Record<string, unknown> = {}) {
  return {
    theme_revision_id: "theme-1",
    theme: "四天工作制在不同行业的实际效果与代价",
    status: "succeeded",
    report: {
      id: "theme-report-1",
      theme_revision_id: "theme-1",
      prompt_version: "theme-zhiyan-prompt-v0.1",
      model: "deepseek-v4-flash",
      created_at: "2026-09-01T18:00:00Z",
      document: themeDocument(),
    },
    execution: null,
    capabilities: {
      can_start: false,
      can_cancel: false,
      retry: { allowed: true, remaining: 2, allowed_at: null },
    },
    ...overrides,
  };
}

function sourceState() {
  return {
    source_revision_id: "revision-1",
    source_title: "城市空气质量年度回顾",
    status: "succeeded",
    report: null,
    execution: null,
    capabilities: {
      can_start: false,
      can_cancel: false,
      retry: { allowed: true, remaining: 2, allowed_at: null },
    },
  };
}

function overview(theme: unknown, liyan: Record<string, unknown>) {
  return {
    task_id: "task-1",
    task_version_id: "version-1",
    task_version_number: 1,
    sources: [sourceState()],
    theme,
    liyan,
  };
}

function respondWith(...payloads: unknown[]) {
  type FetchCall = (target: unknown, options?: unknown) => Promise<Response>;
  const fetchMock = vi.fn<FetchCall>(async () => {
    const payload = payloads.length > 1 ? payloads.shift() : payloads[0];
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("ThemeReportView", () => {
  it("renders the six sections with “知”盲点 above the rest", () => {
    render(<ThemeReportView document={themeDocument()} theme="主题" idPrefix="theme-1" />);

    const headings = screen
      .getAllByRole("heading", { level: 4 })
      .map((heading) => heading.textContent);

    expect(headings).toEqual([
      "概要",
      "“知”盲点",
      "“知”事实",
      "“知”观点",
      "“知”分歧",
      "“知”依据",
    ]);
  });

  it("offers every item as a theme capsule, saying which report it came from", async () => {
    const user = userEvent.setup();
    const onCapsuleSelect = vi.fn();
    render(
      <ThemeReportView
        document={themeDocument()}
        theme="四天工作制"
        idPrefix="theme-1"
        taskVersionId="version-1"
        reportId="theme-report-1"
        onCapsuleSelect={onCapsuleSelect}
      />,
    );

    await user.click(screen.getByRole("button", { name: "“知”盲点" }));
    await user.click(await screen.findByRole("button", { name: "插入 TB-01 到立言指令" }));

    expect(onCapsuleSelect).toHaveBeenCalledWith({
      label: "主题 · TB-01",
      reference: {
        type: "capsule",
        task_version_id: "version-1",
        report_id: "theme-report-1",
        item_id: "TB-01",
        report_kind: "theme",
      },
    });
  });

  it("shows what the sources do with each blind spot", async () => {
    const user = userEvent.setup();
    render(<ThemeReportView document={themeDocument()} theme="主题" idPrefix="theme-1" />);

    await user.click(screen.getByRole("button", { name: "“知”盲点" }));

    expect(
      await screen.findByText("三个来源均未提及连续生产行业的排班安排。"),
    ).toBeInTheDocument();
  });
});

describe("TaskZhiyanArea with a theme", () => {
  it("lists the theme first and counts it in the progress line", async () => {
    respondWith(
      overview(themeState(), { can_generate: true, unavailable_reason: null }),
    );
    const onZhiyanState = vi.fn();

    render(
      <TaskZhiyanArea
        accessToken="token"
        taskId="task-1"
        onZhiyanState={onZhiyanState}
      />,
    );

    const tabs = await screen.findByRole("tablist", { name: "知言报告" });
    const [first] = within(tabs).getAllByRole("tab");
    expect(first).toHaveTextContent("主题");
    await waitFor(() =>
      expect(onZhiyanState).toHaveBeenCalledWith(
        expect.objectContaining({ done: 2, total: 2, liyanReady: true }),
      ),
    );
  });

  it("keeps the gate shut and names the way out when the theme report failed", async () => {
    respondWith(
      overview(
        themeState({
          status: "failed",
          report: null,
          execution: {
            id: "execution-9",
            operation: "analyze_theme",
            status: "failed",
            attempt: 2,
            input_version: 1,
            trace_id: "trace-9",
            created_at: "2026-09-01T18:00:00Z",
            started_at: "2026-09-01T18:00:01Z",
            finished_at: "2026-09-01T18:02:00Z",
            cancellation_requested_at: null,
            result_id: null,
            error: { code: "busy", message: "服务繁忙，请重试。" },
          },
          capabilities: {
            can_start: false,
            can_cancel: false,
            retry: { allowed: false, remaining: 0, allowed_at: null },
          },
        }),
        {
          can_generate: false,
          unavailable_reason:
            "主题还没有成功的知言报告，可重试；若始终失败，可在编辑来源时清空主题后保存。",
        },
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(
      await screen.findByText(
        "若主题报告始终失败，可在编辑来源时清空主题后保存，立言即可继续。",
      ),
    ).toBeInTheDocument();
  });

  it("renders no theme tab for a version that has none", async () => {
    respondWith(overview(null, { can_generate: true, unavailable_reason: null }));

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    const tabs = await screen.findByRole("tablist", { name: "知言报告" });
    expect(within(tabs).getAllByRole("tab")).toHaveLength(1);
    expect(screen.queryByText("主题")).not.toBeInTheDocument();
  });
});

describe("ThemeChoice", () => {
  it("offers no press while 提炼主题 is hidden, and asks for nothing", async () => {
    const fetchMock = respondWith({});

    render(
      <ThemeChoice
        accessToken="token"
        clientSessionId="session-1"
        theme=""
        onThemeChange={vi.fn()}
        canPropose
        disabledReason={null}
      />,
    );

    expect(screen.queryByRole("button", { name: /提炼主题/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "提炼主题" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("使用 AI 从来源中提炼共同主题，从3个候选中选择。"),
    ).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("still confirms a 主题 the writer types, which is now the only way in", async () => {
    const user = userEvent.setup();
    const onThemeChange = vi.fn();

    render(
      <ThemeChoice
        accessToken="token"
        clientSessionId="session-1"
        theme=""
        onThemeChange={onThemeChange}
        canPropose={false}
        disabledReason="请先添加来源，全部抓取成功后才能提炼主题。"
      />,
    );

    await user.type(screen.getByLabelText("主题"), "四");

    expect(onThemeChange).toHaveBeenCalledWith("四");
    // The reason a press is unavailable is not worth a line when there is no
    // press to explain.
    expect(
      screen.queryByText("请先添加来源，全部抓取成功后才能提炼主题。"),
    ).not.toBeInTheDocument();
  });
});
