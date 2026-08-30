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
    if (path.endsWith("/account/usage")) return Response.json({ entries: [], has_more: false });
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
