import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ZhiyanPanel } from "./ZhiyanPanel";
import { ZhiyanReportView, type ZhiyanReportDocument } from "./ZhiyanReportView";

function reportDocument(overrides: Partial<ZhiyanReportDocument> = {}): ZhiyanReportDocument {
  return {
    overview: "这篇来源混合了统计声明与作者立场。",
    source: {
      title: "城市空气质量年度回顾",
      origin: "示例日报",
      material_type: "新闻评论",
      context: "发表于年度环境公报之后。",
    },
    facts: {
      items: [
        {
          id: "F1",
          claim: "细颗粒物年均浓度下降百分之十二。",
          verdict: "supported",
          reasoning: "官方公报给出相同降幅。",
          evidence_refs: ["E1"],
        },
        {
          id: "F2",
          claim: "新规使工业排放减半。",
          verdict: "unverifiable",
          reasoning: "未找到可靠公开数据。",
          evidence_refs: [],
        },
      ],
      empty_statement: null,
    },
    viewpoints: { items: [], empty_statement: "来源中没有可归属的观点表达。" },
    logic: {
      items: [
        {
          id: "L1",
          finding: "以时间先后推断因果。",
          assessment: "同期发生不足以证明因果关系。",
          refs: ["F1"],
        },
      ],
      empty_statement: null,
    },
    intent: { items: [], empty_statement: "没有可支持的意图判断。" },
    evidence: {
      items: [
        {
          id: "E1",
          title: "年度环境公报",
          url: "https://gov.example/report",
          publisher: "示例市生态环境局",
          relevance: "给出官方年度降幅。",
        },
      ],
      empty_statement: null,
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
      model: "deepseek-v4-pro",
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

    for (const heading of ["总览", "来源", "事实", "观点", "逻辑", "意图", "证据"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    expect(screen.getAllByText("F1")).toHaveLength(2);
    expect(screen.getByText("属实")).toBeInTheDocument();
    expect(screen.getByText("暂时无法核实")).toBeInTheDocument();
    expect(screen.getByText("L1")).toBeInTheDocument();
  });

  it("states why an empty section is empty", () => {
    render(<ZhiyanReportView document={reportDocument()} sourceTitle="来源一" idPrefix="report-1" />);

    expect(screen.getByText("来源中没有可归属的观点表达。")).toBeInTheDocument();
    expect(screen.getByText("没有可支持的意图判断。")).toBeInTheDocument();
  });

  it("links only plain web evidence addresses", () => {
    render(
      <ZhiyanReportView
        document={reportDocument({
          evidence: {
            items: [
              {
                id: "E1",
                title: "年度环境公报",
                url: "https://gov.example/report",
                publisher: "示例市生态环境局",
                relevance: "给出官方年度降幅。",
              },
              {
                id: "E2",
                title: "可疑地址",
                url: "javascript:alert(1)",
                publisher: "未知",
                relevance: "不应成为链接。",
              },
            ],
            empty_statement: null,
          },
        })}
        sourceTitle="来源一"
        idPrefix="report-1"
      />,
    );

    const link = screen.getByRole("link", { name: "https://gov.example/report" });
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.queryByRole("link", { name: /javascript/ })).not.toBeInTheDocument();
    expect(screen.getByText(/该证据地址不可作为链接打开/)).toBeInTheDocument();
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
        document={reportDocument({ overview: "<img src=x onerror=alert(1)>注意" })}
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
      within(screen.getByLabelText("知言报告 来源一")).getAllByText("F1"),
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
