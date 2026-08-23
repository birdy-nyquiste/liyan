import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ZhiyanReportView, type ZhiyanReportDocument } from "./ZhiyanReportView";
import { TaskZhiyanArea } from "./TaskZhiyanArea";

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
    capabilities: {
      can_start: false,
      can_cancel: false,
      retry: { allowed: true, remaining: 2, allowed_at: null },
    },
    ...overrides,
  };
}

function execution(overrides: Record<string, unknown> = {}) {
  return {
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
    ...overrides,
  };
}

function overviewResponse(sources: unknown[], liyan: Record<string, unknown>) {
  return {
    task_id: "task-1",
    task_version_id: "version-1",
    task_version_number: 1,
    sources,
    liyan,
  };
}

const LIYAN_OPEN = { can_generate: true, unavailable_reason: null };
const LIYAN_INCOMPLETE = {
  can_generate: false,
  unavailable_reason: "仍有来源没有成功的知言报告，全部成功后才能生成立言。",
};
const LIYAN_WAITING = {
  can_generate: false,
  unavailable_reason: "知言分析尚未全部完成，全部报告成功后才能生成立言。",
};

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

describe("TaskZhiyanArea", () => {
  it("renders a succeeded report with no retry or terminate action", async () => {
    respondWith(overviewResponse([stateResponse()], LIYAN_OPEN));

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    expect(screen.getByText(/不可编辑或重新生成/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /重试|终止|开始/ })).not.toBeInTheDocument();
    expect(
      within(screen.getByLabelText("知言报告 城市空气质量年度回顾")).getAllByText("F-01"),
    ).not.toHaveLength(0);
  });

  it("offers each F V L I item as a stable current-version capsule", async () => {
    respondWith(overviewResponse([stateResponse()], LIYAN_OPEN));
    const user = userEvent.setup();
    const onCapsuleSelect = vi.fn();

    render(
      <TaskZhiyanArea
        accessToken="token"
        taskId="task-1"
        onCapsuleSelect={onCapsuleSelect}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "插入 F-01 到立言指令" }));

    expect(onCapsuleSelect).toHaveBeenCalledWith({
      label: "城市空气质量年度回顾 · F-01",
      reference: {
        type: "capsule",
        task_version_id: "version-1",
        report_id: "report-1",
        item_id: "F-01",
      },
    });
  });

  it("keeps a succeeded report readable while another source has failed", async () => {
    respondWith(
      overviewResponse(
        [
          stateResponse(),
          stateResponse({
            source_revision_id: "revision-2",
            source_title: "四天工作制已经没有争议",
            status: "failed",
            report: null,
            execution: execution({
              id: "execution-2",
              status: "failed",
              attempt: 2,
              finished_at: "2026-08-22T18:00:09Z",
              error: { code: "provider_unavailable", message: "分析服务暂时不可用。" },
            }),
            capabilities: {
              can_start: true,
              can_cancel: false,
              retry: { allowed: true, remaining: 2, allowed_at: null },
            },
          }),
        ],
        LIYAN_INCOMPLETE,
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    const succeeded = screen.getByLabelText("知言报告 城市空气质量年度回顾");
    expect(within(succeeded).getAllByText("F-01")).not.toHaveLength(0);
    expect(screen.getByText("分析未完成")).toBeInTheDocument();
  });

  it("shows the one failure message the server allows, and offers a retry", async () => {
    respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "failed",
            report: null,
            execution: execution({
              status: "failed",
              error: { code: "busy", message: "服务繁忙，请重试。" },
            }),
            capabilities: {
              can_start: true,
              can_cancel: false,
              retry: { allowed: true, remaining: 2, allowed_at: null },
            },
          }),
        ],
        LIYAN_INCOMPLETE,
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(await screen.findByRole("alert")).toHaveTextContent("服务繁忙，请重试。");
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
  });

  it("holds the retry button until the moment the server named", async () => {
    respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "failed",
            report: null,
            execution: execution({ status: "failed", attempt: 2 }),
            capabilities: {
              can_start: false,
              can_cancel: false,
              retry: {
                allowed: false,
                remaining: 2,
                allowed_at: new Date(Date.now() + 30_000).toISOString(),
              },
            },
          }),
        ],
        LIYAN_INCOMPLETE,
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(await screen.findByRole("button", { name: "重试" })).toBeDisabled();
    expect(screen.getByText(/秒后可重试，还可重试 2 次。/)).toBeInTheDocument();
  });

  it("says the retry allowance is spent when the server reports none left", async () => {
    respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "failed",
            report: null,
            execution: execution({ status: "failed", attempt: 4 }),
            capabilities: {
              can_start: false,
              can_cancel: false,
              retry: { allowed: false, remaining: 0, allowed_at: null },
            },
          }),
        ],
        LIYAN_INCOMPLETE,
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    expect(await screen.findByText("重试次数已用完，请稍后再试。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeDisabled();
  });

  it("retries the source revision the server named", async () => {
    const running = stateResponse({
      status: "running",
      report: null,
      execution: execution(),
      capabilities: {
        can_start: false,
        can_cancel: true,
        retry: { allowed: false, remaining: 1, allowed_at: null },
      },
    });
    const fetchMock = respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "failed",
            report: null,
            execution: execution({ status: "failed" }),
            capabilities: {
              can_start: true,
              can_cancel: false,
              retry: { allowed: true, remaining: 2, allowed_at: null },
            },
          }),
        ],
        LIYAN_INCOMPLETE,
      ),
      running,
      overviewResponse([running], LIYAN_WAITING),
      overviewResponse([stateResponse()], LIYAN_OPEN),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" pollIntervalMs={1} />);
    await userEvent.click(await screen.findByRole("button", { name: "重试" }));

    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    const started = fetchMock.mock.calls.find(
      ([target, options]) => requestMethod(target, options) === "POST",
    );
    expect(requestUrl(started?.[0])).toContain("/source-revisions/revision-1/zhiyan-runs");
  });

  it("terminates the running execution the server advertises", async () => {
    const cancelled = stateResponse({
      status: "cancelled",
      report: null,
      execution: execution({
        status: "cancelled",
        finished_at: "2026-08-22T18:00:05Z",
        cancellation_requested_at: "2026-08-22T18:00:04Z",
        error: { code: "cancelled", message: "知言分析已取消，可重新发起。" },
      }),
      capabilities: {
        can_start: true,
        can_cancel: false,
        retry: { allowed: true, remaining: 2, allowed_at: null },
      },
    });
    const fetchMock = respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "running",
            report: null,
            execution: execution(),
            capabilities: {
              can_start: false,
              can_cancel: true,
              retry: { allowed: false, remaining: 2, allowed_at: null },
            },
          }),
        ],
        LIYAN_WAITING,
      ),
      { id: "execution-1", status: "cancel_requested" },
      overviewResponse([cancelled], LIYAN_INCOMPLETE),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" pollIntervalMs={5000} />);
    await userEvent.click(await screen.findByRole("button", { name: "终止分析" }));

    expect(await screen.findByText("分析已取消")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("知言分析已取消，可重新发起。");
    expect(
      fetchMock.mock.calls.find(([target]) =>
        requestUrl(target).includes("/executions/execution-1/cancel"),
      ),
    ).toBeDefined();
  });

  it("keeps polling after a poll fails", async () => {
    type FetchCall = (target: unknown, options?: unknown) => Promise<Response>;
    const running = overviewResponse(
      [
        stateResponse({
          status: "running",
          report: null,
          execution: execution(),
          capabilities: {
            can_start: false,
            can_cancel: true,
            retry: { allowed: false, remaining: 2, allowed_at: null },
          },
        }),
      ],
      LIYAN_WAITING,
    );
    let call = 0;
    const fetchMock = vi.fn<FetchCall>(async () => {
      call += 1;
      if (call === 2) return Response.error();
      const payload = call < 3 ? running : overviewResponse([stateResponse()], LIYAN_OPEN);
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" pollIntervalMs={1} />);

    expect(await screen.findByText("分析进行中")).toBeInTheDocument();
    expect(await screen.findByText("分析已完成")).toBeInTheDocument();
    expect(fetchMock.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("says nothing extra when the server refuses a retry that came too soon", async () => {
    type FetchCall = (target: unknown, options?: unknown) => Promise<Response>;
    const failed = overviewResponse(
      [
        stateResponse({
          status: "failed",
          report: null,
          execution: execution({
            status: "failed",
            error: { code: "busy", message: "服务繁忙，请重试。" },
          }),
          capabilities: {
            can_start: true,
            can_cancel: false,
            retry: { allowed: true, remaining: 1, allowed_at: null },
          },
        }),
      ],
      LIYAN_INCOMPLETE,
    );
    const fetchMock = vi.fn<FetchCall>(async (target, options) => {
      if (requestMethod(target, options) === "POST") {
        return new Response(JSON.stringify({ detail: "重试次数已用完，请稍后再试。" }), {
          status: 429,
          headers: { "Content-Type": "application/json", "Retry-After": "30" },
        });
      }
      return new Response(JSON.stringify(failed), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "重试" }));

    await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(1));
    expect(screen.getByRole("alert")).toHaveTextContent("服务繁忙，请重试。");
    expect(screen.queryByText("知言分析未能启动，请稍后重试。")).not.toBeInTheDocument();
  });

  it("holds focus on 知言 while any report is missing", async () => {
    respondWith(
      overviewResponse(
        [
          stateResponse({
            status: "running",
            report: null,
            execution: execution(),
            capabilities: {
              can_start: false,
              can_cancel: true,
              retry: { allowed: false, remaining: 2, allowed_at: null },
            },
          }),
        ],
        LIYAN_WAITING,
      ),
    );

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" />);

    const zhiyan = await screen.findByRole("heading", { name: /共 1 个来源的独立报告/ });
    await waitFor(() => expect(zhiyan).toHaveFocus());
  });

  it("polls only while a run is active and stops at its terminal state", async () => {
    const fetchMock = respondWith(overviewResponse([stateResponse()], LIYAN_OPEN));

    render(<TaskZhiyanArea accessToken="token" taskId="task-1" pollIntervalMs={1} />);
    await screen.findByText("分析已完成");
    await new Promise((resolve) => setTimeout(resolve, 20));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });
});
