import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ZhiyanPanel } from "./ZhiyanPanel";
import { ZhiyanReportView, type ZhiyanReportDocument } from "./ZhiyanReportView";

function reportDocument(overrides: Partial<ZhiyanReportDocument> = {}): ZhiyanReportDocument {
  return {
    overview: {
      content_summary: "原文以英国四天工作制试验为依据，呼吁全面强制实施。",
      fact_check_summary: "共核查 2 项重要事实：1 项部分准确，1 项暂无法核实。",
      key_findings: [{ ref_id: "F-01", text: "35% 不代表所有企业。" }],
      reading_note: "原文引用了真实试验，但改变了指标的适用范围。",
    },
    source: {
      genre: "政策评论",
      provenance: "二手转述",
      completeness: "完整短文",
      note: "原文没有提供试验报告链接。",
    },
    facts: {
      items: [
        {
          id: "F-01",
          quote: "所有企业实行四天工作制后，营收都会增长35%。",
          claim: "英国试验中的所有企业营收均增长 35%。",
          verdict: "部分准确",
          explanation: "35% 是提交数据企业相较往年同期的平均变化。",
          evidence_ids: ["E-01"],
        },
        {
          id: "F-02",
          quote: "员工压力下降71%。",
          claim: "71% 的员工压力下降。",
          verdict: "暂无法核实",
          explanation: "未找到可靠的公开统计口径。",
          evidence_ids: [],
        },
      ],
      empty_state: null,
    },
    viewpoints: { items: [], empty_state: "来源中没有可归属的观点表达。" },
    logic: {
      argument_chain: "试验出现积极结果 → 政府应全面强制实施。",
      items: [
        {
          id: "L-01",
          quote: "数据已经证明四天工作制对所有行业都有效。",
          judgment: "结论超出了试验能够支持的范围。",
          explanation: "特定参与企业的试验不能证明所有行业获得相同结果。",
          related_ids: ["F-01"],
        },
      ],
      empty_state: null,
    },
    intent: {
      explicit_purpose: "支持四天工作制并呼吁政府全面实施。",
      items: [],
      target_audience: "关心劳动政策的公众和决策者。",
      expression_methods: ["使用具体数字增强权威感"],
      empty_state: "没有可支持的额外意图推断。",
    },
    evidence: {
      items: [
        {
          id: "E-01",
          title: "Autonomy: The UK's Four-Day Week Pilot",
          url: "https://autonomy.work/four-day-week-pilot",
          explanation: "说明参与企业数量与营收指标的实际统计口径。",
        },
      ],
      empty_state: null,
    },
    ...overrides,
  };
}

function stateResponse(overrides: Record<string, unknown> = {}) {
  return {
    source_revision_id: "revision-1",
    source_title: "城市空气质量年度回顾",
    status: "succeeded",
    report: {
      id: "report-1",
      source_revision_id: "revision-1",
      prompt_version: "zhiyan-2026-08-22",
      model: "deepseek-v4-flash",
      created_at: "2026-08-22T18:00:00Z",
      document: reportDocument(),
    },
    execution: null,
    capabilities: { can_start: false, can_cancel: false },
    ...overrides,
  };
}

function requestMethod(target: unknown, options: unknown): string {
  if (target instanceof Request) return target.method;
  return (options as RequestInit | undefined)?.method ?? "GET";
}

function requestUrl(target: unknown): string {
  return target instanceof Request ? target.url : String(target);
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
});

describe("ZhiyanReportView", () => {
  it("renders all seven sections with stable identifiers and verdict labels", () => {
    render(<ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />);

    for (const heading of [
      "概要",
      "“知”来源",
      "“知”事实",
      "“知”观点",
      "“知”逻辑",
      "“知”意图",
      "“知”依据",
    ]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText("F-01").length).toBeGreaterThan(1);
    expect(screen.getByText("部分准确")).toBeInTheDocument();
    expect(screen.getByText("暂无法核实")).toBeInTheDocument();
    expect(screen.getByText("L-01")).toBeInTheDocument();
  });

  it("states why an empty section is empty", () => {
    render(<ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />);

    expect(screen.getByText("来源中没有可归属的观点表达。")).toBeInTheDocument();
    expect(screen.getByText("没有可支持的额外意图推断。")).toBeInTheDocument();
  });

  it("shows the source excerpt behind every judgement", () => {
    render(<ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />);

    expect(
      screen.getByText("所有企业实行四天工作制后，营收都会增长35%。"),
    ).toBeInTheDocument();
    expect(screen.getByText("数据已经证明四天工作制对所有行业都有效。")).toBeInTheDocument();
  });

  it("renders the argument chain and intent framing the spec asks for", () => {
    render(<ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />);

    expect(screen.getByText("试验出现积极结果 → 政府应全面强制实施。")).toBeInTheDocument();
    expect(screen.getByText("关心劳动政策的公众和决策者。")).toBeInTheDocument();
    expect(screen.getByText("使用具体数字增强权威感")).toBeInTheDocument();
  });

  it("links only plain web evidence addresses", () => {
    render(
      <ZhiyanReportView
        document={reportDocument({
          evidence: {
            items: [
              {
                id: "E-01",
                title: "Autonomy: The UK's Four-Day Week Pilot",
                url: "https://autonomy.work/four-day-week-pilot",
                explanation: "说明参与企业数量。",
              },
              {
                id: "E-02",
                title: "可疑地址",
                url: "javascript:alert(1)",
                explanation: "不应成为链接。",
              },
            ],
            empty_state: null,
          },
        })}
        sourceTitle="来源一"
        idPrefix="report-1"
      />,
    );

    const link = screen.getByRole("link", {
      name: "Autonomy: The UK's Four-Day Week Pilot",
    });
    expect(link).toHaveAttribute("href", "https://autonomy.work/four-day-week-pilot");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.queryByRole("link", { name: /javascript/ })).not.toBeInTheDocument();
    expect(screen.getByText(/该依据地址不可作为链接打开/)).toBeInTheDocument();
  });

  it("keeps section ids unique when a task shows several reports", () => {
    const { container } = render(
      <>
        <ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />
        <ZhiyanReportView document={reportDocument()} sourceTitle="来源二" idPrefix="report-2" />
      </>,
    );

    const ids = [...container.querySelectorAll("[id]")].map((element) => element.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toContain("report-1-facts");
    expect(ids).toContain("report-2-facts");
  });

  it("renders untrusted report text as text rather than markup", () => {
    render(
      <ZhiyanReportView
        document={reportDocument({
          overview: {
            content_summary: "<img src=x onerror=alert(1)>注意",
            fact_check_summary: "共核查 0 项。",
            key_findings: [],
            reading_note: "留意注入尝试。",
          },
        })}
        sourceTitle="来源一"
        idPrefix="report-1"
      />,
    );

    const report = screen.getByLabelText("知言报告 来源一");
    expect(report.querySelector("img")).toBeNull();
    expect(screen.getByText("<img src=x onerror=alert(1)>注意")).toBeInTheDocument();
  });
});

describe("ZhiyanPanel", () => {
  it("renders a succeeded report with no edit or regenerate action", async () => {
    respondWith(stateResponse());

    render(
      <ZhiyanPanel accessToken="token" sourceRevisionId="revision-1" sourceTitle="来源一" />,
    );

    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    expect(screen.getByText(/不可编辑或重新生成/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /分析/ })).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("知言报告 来源一")).getAllByText("F-01"),
    ).not.toHaveLength(0);
  });

  it("starts a run for a revision that has none", async () => {
    const fetchMock = respondWith(
      stateResponse({
        status: "absent",
        report: null,
        capabilities: { can_start: true, can_cancel: false },
      }),
      stateResponse({
        status: "running",
        report: null,
        execution: {
          id: "execution-1",
          operation: "analyze_source",
          status: "queued",
          attempt: 1,
          input_version: 1,
          trace_id: "trace-1",
          created_at: "2026-08-22T18:00:00Z",
          started_at: null,
          finished_at: null,
          cancellation_requested_at: null,
          result_id: null,
          error: null,
        },
        capabilities: { can_start: false, can_cancel: true },
      }),
      stateResponse(),
    );

    render(
      <ZhiyanPanel
        accessToken="token"
        sourceRevisionId="revision-1"
        sourceTitle="来源一"
        pollIntervalMs={1}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "开始知言分析" }));

    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    const started = fetchMock.mock.calls.find(([target, options]) => requestMethod(target, options) === "POST");
    expect(started).toBeDefined();
    expect(requestUrl(started?.[0])).toContain("/source-revisions/revision-1/zhiyan-runs");
  });

  it("shows a failed run's safe message and offers another attempt", async () => {
    respondWith(
      stateResponse({
        status: "failed",
        report: null,
        execution: {
          id: "execution-1",
          operation: "analyze_source",
          status: "failed",
          attempt: 1,
          input_version: 1,
          trace_id: "trace-1",
          created_at: "2026-08-22T18:00:00Z",
          started_at: "2026-08-22T18:00:01Z",
          finished_at: "2026-08-22T18:00:09Z",
          cancellation_requested_at: null,
          result_id: null,
          error: { code: "provider_unavailable", message: "分析服务暂时不可用，请稍后重试。" },
        },
        capabilities: { can_start: true, can_cancel: false },
      }),
    );

    render(
      <ZhiyanPanel accessToken="token" sourceRevisionId="revision-1" sourceTitle="来源一" />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("分析服务暂时不可用，请稍后重试。");
    expect(screen.getByRole("button", { name: "重新分析" })).toBeInTheDocument();
  });

  it("offers the cancel the server advertises and reports the cancelled outcome", async () => {
    const runningState = stateResponse({
      status: "running",
      report: null,
      execution: {
        id: "execution-1",
        operation: "analyze_source",
        status: "running",
        attempt: 1,
        input_version: 1,
        trace_id: "trace-1",
        created_at: "2026-08-22T18:00:00Z",
        started_at: "2026-08-22T18:00:01Z",
        finished_at: null,
        cancellation_requested_at: null,
        result_id: null,
        error: null,
      },
      capabilities: { can_start: false, can_cancel: true },
    });
    const cancelledState = stateResponse({
      status: "cancelled",
      report: null,
      execution: {
        id: "execution-1",
        operation: "analyze_source",
        status: "cancelled",
        attempt: 1,
        input_version: 1,
        trace_id: "trace-1",
        created_at: "2026-08-22T18:00:00Z",
        started_at: "2026-08-22T18:00:01Z",
        finished_at: "2026-08-22T18:00:05Z",
        cancellation_requested_at: "2026-08-22T18:00:04Z",
        result_id: null,
        error: { code: "cancelled", message: "知言分析已取消，可重新发起。" },
      },
      capabilities: { can_start: true, can_cancel: false },
    });
    const fetchMock = respondWith(
      runningState,
      { id: "execution-1", status: "cancel_requested" },
      cancelledState,
      cancelledState,
    );

    render(
      <ZhiyanPanel
        accessToken="token"
        sourceRevisionId="revision-1"
        sourceTitle="来源一"
        pollIntervalMs={5000}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "取消分析" }));

    expect(await screen.findByText("分析已取消")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("知言分析已取消，可重新发起。");
    expect(screen.getByRole("button", { name: "重新分析" })).toBeInTheDocument();
    const cancelCall = fetchMock.mock.calls.find(([target]) =>
      requestUrl(target).includes("/executions/execution-1/cancel"),
    );
    expect(cancelCall).toBeDefined();
  });

  it("stops polling once the run reaches a terminal state", async () => {
    const fetchMock = respondWith(stateResponse());

    render(
      <ZhiyanPanel
        accessToken="token"
        sourceRevisionId="revision-1"
        sourceTitle="来源一"
        pollIntervalMs={1}
      />,
    );
    await screen.findByText("分析已完成");
    await new Promise((resolve) => setTimeout(resolve, 20));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
