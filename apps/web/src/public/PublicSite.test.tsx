import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import type { AuthProvider } from "../auth/provider";

let token: string | null;
let listeners: Set<(token: string | null) => void>;
let provider: AuthProvider;
beforeEach(() => {
  token = null;
  listeners = new Set();
  window.history.replaceState({}, "", "/");
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  Element.prototype.scrollIntoView = vi.fn();
  provider = {
    getAccessToken: vi.fn(async () => token),
    sendEmailOtp: vi.fn(async () => undefined),
    verifyEmailOtp: vi.fn(async () => { token = "session"; return token; }),
    signOut: vi.fn(async () => { token = null; }),
    onAuthStateChange: vi.fn(listener => { listeners.add(listener); return () => listeners.delete(listener); }),
  };
  vi.stubGlobal("fetch", vi.fn(async (request: Request) => {
    if (request.url.endsWith("/health/live")) return Response.json({ status: "alive" });
    if (request.url.endsWith("/auth/me")) return Response.json({ id: "public-user", email: "writer@example.com" });
    if (request.url.includes("/tasks")) return Response.json({ items: [], next_cursor: null });
    return new Response(null, { status: 404 });
  }));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("public entry routes", () => {
  it("keeps the homepage public and leads new users through the shared OTP flow", async () => {
    const user = userEvent.setup();
    render(<App authProvider={provider} />);
    const links = await screen.findAllByRole("link", { name: "立即体验" });
    // What the hero's button costs, said under the button itself. Queried by
    // class rather than by text: the same words appear in 价格, and the rule
    // being fixed here is which of the two states shows this one.
    expect(document.querySelector(".site-actions-note")).toHaveTextContent("注册即赠送额度");
    expect(screen.queryByLabelText("邮箱")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "注册" })).not.toBeInTheDocument();
    await user.click(links[0]);
    expect(window.location.pathname).toBe("/sign-in");
    await user.type(await screen.findByLabelText("邮箱"), "writer@example.com");
    await user.click(screen.getByRole("button", { name: "发送验证码" }));
    await user.type(await screen.findByLabelText("验证码"), "123456");
    await user.click(screen.getByRole("button", { name: "登录" }));
    expect(await screen.findByRole("heading", { name: "新建立言任务" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/task");
    expect(provider.sendEmailOtp).toHaveBeenCalledTimes(1);
  });

  it("lets an authenticated visitor choose when to enter the workbench", async () => {
    token = "session";
    const user = userEvent.setup();
    render(<App authProvider={provider} />);
    const links = await screen.findAllByRole("link", { name: "前往工作台" });
    // Nothing is granted to a user who signed up long ago, so the hero does
    // not offer it to them.
    expect(document.querySelector(".site-actions-note")).toBeNull();
    expect(window.location.pathname).toBe("/");
    expect(screen.queryByRole("link", { name: "立即体验" })).not.toBeInTheDocument();
    for (const link of links) expect(link).toHaveAttribute("href", "/task");
    await user.click(links[0]);
    expect(await screen.findByRole("heading", { name: "新建立言任务" })).toBeInTheDocument();
    expect(provider.sendEmailOtp).not.toHaveBeenCalled();
  });

  it("updates every CTA when a session starts or ends in another tab", async () => {
    render(<App authProvider={provider} />);
    await screen.findAllByRole("link", { name: "立即体验" });
    token = "session";
    await act(async () => { listeners.forEach(listener => listener(token)); });
    expect((await screen.findAllByRole("link", { name: "前往工作台" })).length).toBe(4);
    token = null;
    await act(async () => { listeners.forEach(listener => listener(null)); });
    expect((await screen.findAllByRole("link", { name: "立即体验" })).length).toBe(4);
  });

  it("keeps legal pages public and returns their navigation to homepage sections", async () => {
    const user = userEvent.setup();
    render(<App authProvider={provider} />);
    await user.click(screen.getByRole("link", { name: "使用条款" }));
    expect(window.location.pathname).toBe("/terms");
    expect(screen.getByRole("heading", { name: "使用条款" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "四、你的内容" })).toBeInTheDocument();
    // Scoped to the footer: both documents link to each other, so more than one
    // link by this name is the expected state rather than an ambiguity to fix.
    const legalNav = screen.getByRole("navigation", { name: "法律与联系" });
    await user.click(within(legalNav).getByRole("link", { name: "隐私政策" }));
    expect(window.location.pathname).toBe("/privacy");
    expect(screen.getByRole("heading", { name: "隐私政策" })).toBeInTheDocument();
    // The parts of this page the Chrome Web Store's review depends on. Its
    // Limited Use policy requires that statement to be on the privacy policy
    // itself rather than only in the developer dashboard, and the listing's
    // data disclosures have to agree with what 第三章 and 第四章 say — so these
    // are not decorative paragraphs, they are why the extension is publishable.
    expect(screen.getByRole("heading", { name: "三、浏览器插件" })).toBeInTheDocument();
    expect(screen.getByText(/Limited Use 要求/)).toBeInTheDocument();
    expect(screen.getByText(/没有内容脚本/)).toBeInTheDocument();
    // The cross-border disclosure, and the recipient it is about.
    expect(screen.getByRole("heading", { name: /五、存储地点、保存期限与跨境传输/ })).toBeInTheDocument();
    expect(screen.getByText(/DeepSeek/)).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "价格" }));
    expect(window.location.pathname + window.location.hash).toBe("/#pricing");
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(screen.getByRole("link", { name: "联系我们" })).toHaveAttribute("href", "mailto:birdyyao@nyquiste.com");
  });

  it("keeps every report section named and its worked example folded away", async () => {
    const user = userEvent.setup();
    render(<App authProvider={provider} />);
    const source = screen.getByRole("article", { name: "来源知言报告" });
    const theme = screen.getByRole("article", { name: "主题知言报告" });
    expect(within(source).getAllByRole("heading", { level: 5 }).map(h => h.textContent)).toEqual(["概要", "“知”来源", "“知”事实", "“知”观点", "“知”逻辑", "“知”意图", "“知”依据"]);
    expect(within(theme).getAllByRole("heading", { level: 5 }).map(h => h.textContent)).toEqual(["概要", "“知”盲点", "“知”事实", "“知”观点", "“知”分歧", "“知”依据"]);
    // What a section is for stays on the page; the worked example folds away.
    // Every example starts folded: what this stage shows is the sections a
    // 知言报告 has, and the example is there for whoever wants one.
    expect(within(source).getByText("内容概要")).not.toBeVisible();
    await user.click(within(source).getAllByText("查看示例")[0]);
    expect(within(source).getByText("内容概要")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "语言: 中文" }));
    expect(screen.getByRole("link", { name: "How it works" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en");
    await user.click(screen.getByRole("button", { name: "Mode: Light" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});
