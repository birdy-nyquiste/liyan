import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AccountPage } from "./AccountPage";

const PACKS = [
  { price_id: "price_small", credits: 2_000, unit_amount: 500, currency: "usd" },
  { price_id: "price_large", credits: 20_000, unit_amount: 5_000, currency: "usd" },
];

/** A server whose balance is whatever the test says it is, when it is asked. */
function respondWith({
  balances = [0],
  checkoutStatus = 200,
}: {
  balances?: number[];
  checkoutStatus?: number;
} = {}) {
  type FetchCall = (request: Request) => Promise<Response>;
  const requests: Request[] = [];
  let read = 0;
  const fetchMock = vi.fn<FetchCall>(async (request) => {
    requests.push(request.clone());
    const path = new URL(request.url).pathname;
    if (path.endsWith("/account/credit-packs")) return Response.json({ packs: PACKS });
    if (path.endsWith("/account/usage")) {
      return Response.json({ entries: [], has_more: false, total: 0, page_size: 20 });
    }
    if (path.endsWith("/account/checkout-session")) {
      if (checkoutStatus !== 200) {
        return Response.json({ detail: "支付服务暂时无法访问。" }, { status: checkoutStatus });
      }
      return Response.json({ url: "https://checkout.stripe.com/c/pay/cs_test_1" });
    }
    const balance = balances[Math.min(read, balances.length - 1)];
    read += 1;
    return Response.json({ remaining_credits: balance, is_paying_user: balance > 0 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return requests;
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AccountPage accessToken="token" />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

describe("AccountPage", () => {
  it("offers the 额度包 the server sells, with both halves of the exchange", async () => {
    respondWith();

    renderAt("/account");

    expect(await screen.findByText("$5.00")).toBeInTheDocument();
    expect(screen.getByText("2,000 额度")).toBeInTheDocument();
    expect(screen.getByText("20,000 额度")).toBeInTheDocument();
  });

  it("sends only the Price to open Checkout, never an amount", async () => {
    // The rule the whole integration is built around: what a payment buys is
    // decided on the server, from a mapping the client never sees.
    const requests = respondWith();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });

    renderAt("/account");
    await userEvent.click((await screen.findAllByRole("button", { name: "购买" }))[0]);

    await waitFor(() => expect(assign).toHaveBeenCalled());
    const opened = requests.find((request) =>
      new URL(request.url).pathname.endsWith("/account/checkout-session"),
    );
    const body = await opened!.json();
    expect(body).toEqual({ price_id: "price_small" });
  });

  it("waits for the webhook rather than reading the balance once", async () => {
    // The redirect routinely beats the webhook. A return that simply read the
    // balance would show the old number and read as a payment that failed.
    respondWith({ balances: [0, 0, 2_000] });
    sessionStorage.setItem("liyan.checkout.baseline", "0");

    renderAt("/account?checkout=cs_test_1");

    expect(await screen.findByText("支付已收到，正在确认额度…")).toBeInTheDocument();
    // Two polls at a second each, so this outlasts the default one-second wait.
    expect(await screen.findByText("额度已到账。", {}, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByText("2,000")).toBeInTheDocument();
  });

  it("never calls a slow settlement a failed payment", async () => {
    // Alipay and WeChat Pay settle late by design. The money has left the
    // user's account, so of everything this could say, 支付失败 is the worst.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      respondWith({ balances: [0] });
      sessionStorage.setItem("liyan.checkout.baseline", "0");

      renderAt("/account?checkout=cs_test_1");
      await vi.advanceTimersByTimeAsync(30_000);

      await waitFor(() =>
        expect(
          screen.getByText("支付已收到，额度稍后到账。你可以先离开这里。"),
        ).toBeInTheDocument(),
      );
      expect(screen.queryByText(/支付失败/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("says a cancelled purchase cost nothing", async () => {
    respondWith();

    renderAt("/account?checkout=cancelled");

    expect(await screen.findByText("本次购买已取消，未产生扣款。")).toBeInTheDocument();
  });

  it("says so when Checkout cannot be opened, and charges nobody", async () => {
    respondWith({ checkoutStatus: 503 });
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });

    renderAt("/account");
    await userEvent.click((await screen.findAllByRole("button", { name: "购买" }))[0]);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "暂时无法前往支付页面，请稍后重试。",
    );
    expect(assign).not.toHaveBeenCalled();
  });

  it("offers no dead button when this deployment sells nothing", async () => {
    type FetchCall = (request: Request) => Promise<Response>;
    vi.stubGlobal(
      "fetch",
      vi.fn<FetchCall>(async (request) => {
        const path = new URL(request.url).pathname;
        if (path.endsWith("/account/credit-packs")) return Response.json({ packs: [] });
        if (path.endsWith("/account/usage")) {
          return Response.json({ entries: [], has_more: false });
        }
        return Response.json({ remaining_credits: 150, is_paying_user: false });
      }),
    );

    renderAt("/account");

    expect(await screen.findByText("购买功能尚未开放。")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "购买" })).not.toBeInTheDocument();
  });
});

/**
 * 使用记录 is a ledger, and a ledger is read backwards as often as forwards.
 *
 * These are written against a server that has more rows than one page holds,
 * which is what the rest of this file's fixture never had — and is why a page
 * that showed no pager at all went unnoticed.
 */
describe("AccountPage 使用记录 pagination", () => {
  const PAGE_SIZE = 20;

  function ledger(total: number) {
    type FetchCall = (request: Request) => Promise<Response>;
    const asked: number[] = [];
    const fetchMock = vi.fn<FetchCall>(async (request) => {
      const url = new URL(request.url);
      if (url.pathname.endsWith("/account/credit-packs")) return Response.json({ packs: [] });
      if (url.pathname.endsWith("/account/usage")) {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        asked.push(offset);
        const rows = Array.from(
          { length: Math.max(0, Math.min(PAGE_SIZE, total - offset)) },
          (_unused, index) => ({
            id: `entry-${offset + index}`,
            kind: "capture",
            description: `第 ${offset + index + 1} 条`,
            task_id: null,
            status: "none",
            amount: -3,
            happened_at: "2026-09-02T10:00:00Z",
          }),
        );
        return Response.json({
          entries: rows,
          has_more: offset + rows.length < total,
          total,
          page_size: PAGE_SIZE,
        });
      }
      return Response.json({ remaining_credits: 100, is_paying_user: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    return asked;
  }

  it("shows one page at a time and says where in the ledger it is", async () => {
    ledger(45);
    renderAt("/account");

    expect(await screen.findByText("第 1 条")).toBeInTheDocument();
    expect(screen.getByText("第 1 / 3 页 · 共 45 条")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(PAGE_SIZE);
    expect(screen.queryByText("第 21 条")).not.toBeInTheDocument();
  });

  it("turns forward and back, replacing the rows rather than piling them up", async () => {
    const user = userEvent.setup();
    ledger(45);
    renderAt("/account");
    await screen.findByText("第 1 条");

    await user.click(screen.getByRole("button", { name: "下一页" }));

    expect(await screen.findByText("第 21 条")).toBeInTheDocument();
    expect(screen.queryByText("第 1 条")).not.toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(PAGE_SIZE);
    expect(screen.getByText("第 2 / 3 页 · 共 45 条")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "上一页" }));

    expect(await screen.findByText("第 1 条")).toBeInTheDocument();
    expect(screen.queryByText("第 21 条")).not.toBeInTheDocument();
  });

  it("cannot be turned past either end", async () => {
    const user = userEvent.setup();
    ledger(25);
    renderAt("/account");
    await screen.findByText("第 1 条");

    // The first page has nothing before it.
    expect(screen.getByRole("button", { name: "上一页" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("第 21 条");

    // The last page holds the remainder and offers nothing after it.
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一页" })).toBeEnabled();
  });

  it("says a ledger that fits on one page is one page", async () => {
    ledger(6);
    renderAt("/account");

    expect(await screen.findByText("第 1 条")).toBeInTheDocument();
    // Present, not hidden: "this is everything" and "this is the beginning of
    // something" are different answers, and a control that only appears when
    // the list spills gives neither.
    expect(screen.getByText("第 1 / 1 页 · 共 6 条")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();
  });

  it("offers no pager at all when nothing has been used", async () => {
    ledger(0);
    renderAt("/account");

    expect(await screen.findByText("还没有使用记录")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "下一页" })).not.toBeInTheDocument();
  });

  it("asks the server for the page it is on, and only for that page", async () => {
    const user = userEvent.setup();
    const asked = ledger(45);
    renderAt("/account");
    await screen.findByText("第 1 条");

    await user.click(screen.getByRole("button", { name: "下一页" }));
    await screen.findByText("第 21 条");

    expect(asked.filter((offset) => offset === 20)).toHaveLength(1);
    expect(asked.every((offset) => offset % PAGE_SIZE === 0)).toBe(true);
  });
});
