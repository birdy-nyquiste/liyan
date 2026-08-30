import { useCallback, useEffect, useRef, useState } from "react";
import { CreditCard } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import {
  createCheckoutSession,
  getAccount,
  listAccountUsage,
  listCreditPacks,
  type AccountResponse,
  type CreditPack,
  type UsageEntry,
  type AccessToken,
} from "../api/client";
import { useInterfaceLocale } from "../interfaceLocale";
import { CHECKOUT_POLL_MS, CHECKOUT_POLL_TIMEOUT_MS } from "./pollIntervals";

const copy = {
  zh: {
    title: "账户",
    remaining: "剩余额度",
    unit: "额度",
    packs: "购买额度",
    packsClosed: "购买功能尚未开放。",
    buy: "购买",
    opening: "正在前往支付…",
    checkoutFailed: "暂时无法前往支付页面，请稍后重试。",
    // Never 支付失败. The money has left their account; of everything this
    // product could say at that moment, that is the worst.
    confirming: "支付已收到，正在确认额度…",
    credited: "额度已到账。",
    pending: "支付已收到，额度稍后到账。你可以先离开这里。",
    cancelled: "本次购买已取消，未产生扣款。",
    history: "使用记录",
    empty: "还没有使用记录",
    loadMore: "加载更多",
    failed: "账户信息加载失败，请稍后重试。",
    locked: "购买额度后可使用公共文章链接与上传文件作为来源。",
    spends: "来源抓取，知言报告生成，立言文章生成会消耗额度，按量计算。",
    running: "进行中",
    done: "已完成",
    failedRun: "失败",
  },
  en: {
    title: "Account",
    remaining: "Credits remaining",
    unit: "credits",
    packs: "Buy credits",
    packsClosed: "Buying is not open yet.",
    buy: "Buy",
    opening: "Opening checkout…",
    checkoutFailed: "Checkout could not be opened. Try again shortly.",
    confirming: "Payment received. Confirming your credits…",
    credited: "Your credits have arrived.",
    pending: "Payment received. Your credits will arrive shortly — you can leave this page.",
    cancelled: "This purchase was cancelled. You have not been charged.",
    history: "Usage history",
    empty: "Nothing used yet",
    loadMore: "Load more",
    failed: "The account could not be loaded. Try again shortly.",
    locked: "Buying credits unlocks article links and uploaded files as sources.",
    spends: "Capturing a 来源, generating a 知言报告, and generating a 立言文章 spend credits, metered by usage.",
    running: "Running",
    done: "Done",
    failedRun: "Failed",
  },
} as const;

/**
 * The balance as it stood when the user left for Stripe.
 *
 * Kept because the return is a fresh page load with no memory of what the
 * number was, and "has it changed" is the only question the return can actually
 * answer — the webhook that credits is on its own schedule, and the redirect
 * routinely arrives first.
 */
const BASELINE_KEY = "liyan.checkout.baseline";

function rememberBaseline(credits: number): void {
  try {
    window.sessionStorage.setItem(BASELINE_KEY, String(credits));
  } catch {
    // A browser refusing storage costs the return its baseline, not the
    // payment. It falls back to waiting the same timeout and saying the same
    // reassuring thing.
  }
}

function baselineBalance(): number | null {
  try {
    const stored = window.sessionStorage.getItem(BASELINE_KEY);
    return stored === null ? null : Number(stored);
  } catch {
    return null;
  }
}

function forgetBaseline(): void {
  try {
    window.sessionStorage.removeItem(BASELINE_KEY);
  } catch {
    // Nothing to do, and nothing that depends on it.
  }
}

/** What the page is doing about a return from Checkout, if anything. */
type ReturnState = "none" | "confirming" | "credited" | "pending" | "cancelled";

function priceLabel(pack: CreditPack): string {
  if (pack.unit_amount === null || pack.currency === null) return "";
  const amount = pack.unit_amount / 100;
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency: pack.currency.toUpperCase(),
    }).format(amount);
  } catch {
    return `${amount} ${pack.currency.toUpperCase()}`;
  }
}

export function AccountPage({ accessToken }: { accessToken: AccessToken }): React.ReactElement {
  const { locale } = useInterfaceLocale();
  const text = copy[locale];
  const [searchParams, setSearchParams] = useSearchParams();
  const [account, setAccount] = useState<AccountResponse | null>(null);
  const [packs, setPacks] = useState<CreditPack[]>([]);
  const [entries, setEntries] = useState<UsageEntry[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);
  const [checkoutFailed, setCheckoutFailed] = useState(false);
  const [returnState, setReturnState] = useState<ReturnState>("none");
  //: Read once, then dropped from the URL, so a reload is not a second return.
  const checkout = useRef(searchParams.get("checkout"));
  /*
    Held in a ref rather than named as a dependency. `setSearchParams` takes a
    new identity whenever the location changes — including from this effect's
    own rewrite of the URL — and depending on it tore the poll down one tick
    after starting it, which looked exactly like a payment that never landed.
  */
  const rewriteUrl = useRef(setSearchParams);
  rewriteUrl.current = setSearchParams;

  const load = useCallback(async () => {
    try {
      const [next, usage] = await Promise.all([
        getAccount(accessToken),
        listAccountUsage(accessToken),
      ]);
      setAccount(next);
      setEntries(usage.entries);
      setHasMore(usage.has_more);
      setFailed(false);
      return next;
    } catch {
      setFailed(true);
      return null;
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Empty is a legitimate answer — a deployment that sells nothing — so a
    // failure here is not distinguished from it. Either way there is nothing
    // to buy, and the page says so rather than offering a dead button.
    listCreditPacks(accessToken)
      .then(setPacks)
      .catch(() => setPacks([]));
  }, [accessToken]);

  /**
   * Wait for the webhook, and stop waiting without ever calling it a failure.
   *
   * Fulfillment happens on the webhook, deliberately — a user who closes the
   * tab after paying has still paid. But Checkout also redirects them back, and
   * that redirect frequently arrives first, so a return that simply read the
   * balance would show the old number and read as a payment that failed.
   */
  useEffect(() => {
    const returned = checkout.current;
    if (returned === null) return;
    // Read and spent: a reload should not replay the return.
    checkout.current = null;
    rewriteUrl.current(
      (current) => {
        const next = new URLSearchParams(current);
        next.delete("checkout");
        return next;
      },
      { replace: true },
    );

    if (returned === "cancelled") {
      forgetBaseline();
      setReturnState("cancelled");
      return;
    }

    const before = baselineBalance();
    setReturnState("confirming");
    let stopped = false;
    const startedAt = Date.now();

    const poll = async (): Promise<void> => {
      if (stopped) return;
      const next = await load();
      if (stopped) return;
      if (next !== null && (before === null || next.remaining_credits !== before)) {
        forgetBaseline();
        setReturnState("credited");
        return;
      }
      if (Date.now() - startedAt >= CHECKOUT_POLL_TIMEOUT_MS) {
        // Not an error. The money has left their account.
        forgetBaseline();
        setReturnState("pending");
        return;
      }
      timer = window.setTimeout(() => void poll(), CHECKOUT_POLL_MS);
    };

    let timer = window.setTimeout(() => void poll(), CHECKOUT_POLL_MS);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [load]);

  const buy = async (pack: CreditPack) => {
    setOpening(pack.price_id);
    setCheckoutFailed(false);
    // Remembered before leaving, because the page that comes back has no memory
    // of what the balance was.
    rememberBaseline(account?.remaining_credits ?? 0);
    try {
      window.location.assign(await createCheckoutSession(accessToken, pack.price_id));
    } catch {
      forgetBaseline();
      setCheckoutFailed(true);
      setOpening(null);
    }
  };

  const loadMore = async () => {
    setBusy(true);
    try {
      const usage = await listAccountUsage(accessToken, entries.length);
      setEntries((current) => [...current, ...usage.entries]);
      setHasMore(usage.has_more);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  const statusLabel: Record<UsageEntry["status"], string | null> = {
    running: text.running,
    done: text.done,
    failed: text.failedRun,
    none: null,
  };

  const returnMessage: Record<ReturnState, string | null> = {
    none: null,
    confirming: text.confirming,
    credited: text.credited,
    pending: text.pending,
    cancelled: text.cancelled,
  };

  return (
    <section className="account-page" aria-labelledby="account-heading">
      <h1 id="account-heading">{text.title}</h1>
      {failed ? <p role="alert">{text.failed}</p> : null}

      <div className="account-balance">
        <span className="account-balance__label">{text.remaining}</span>
        {/*
          A bare integer. No "about N articles" reading beside it: that would
          come from a median, and the people likeliest to lean on it are working
          with long 来源, for whom it is most wrong.
        */}
        <output className="account-balance__value" aria-live="polite">
          {account ? account.remaining_credits.toLocaleString() : "—"}
        </output>
      </div>

      {/*
        What takes 额度, where the balance is. Nothing quotes a price before an
        act and 使用记录 only explains one afterwards, so this is the only place
        that says charging happens at all.
      */}
      <p className="account-spending">{text.spends}</p>

      <h2>{text.packs}</h2>
      {/*
        The return from Checkout, and it is never an alert: none of these
        states is an error, including the one where the 额度 have not arrived
        yet. `aria-live` announces it because the user is waiting on it.
      */}
      {returnMessage[returnState] ? (
        <p className="account-checkout" data-state={returnState} aria-live="polite">
          {returnMessage[returnState]}
        </p>
      ) : null}
      {packs.length === 0 ? (
        <p className="account-packs__note">{text.packsClosed}</p>
      ) : (
        <ul className="account-packs">
          {packs.map((pack) => (
            <li key={pack.price_id} className="account-pack">
              <span className="account-pack__price">{priceLabel(pack)}</span>
              <span className="account-pack__credits">
                {pack.credits.toLocaleString()} {text.unit}
              </span>
              <button
                className="button"
                type="button"
                disabled={opening !== null}
                onClick={() => void buy(pack)}
              >
                {opening === pack.price_id ? text.opening : text.buy}
              </button>
            </li>
          ))}
        </ul>
      )}
      {checkoutFailed ? <p role="alert">{text.checkoutFailed}</p> : null}
      {!account?.is_paying_user ? (
        <p className="account-entitlement">{text.locked}</p>
      ) : null}

      <h2>{text.history}</h2>
      {entries.length === 0 ? (
        <p className="account-empty">{text.empty}</p>
      ) : (
        <ul className="account-usage">
          {entries.map((entry) => (
            <li key={entry.id} className="account-usage__row">
              {/*
                The act's name is the link. It leads to the 立言任务 the act
                belongs to, which is where anything more about it lives — the
                row used to append the 来源's title instead, naming the same
                thing twice and taking you nowhere.
              */}
              {entry.task_id ? (
                <Link className="account-usage__what" to={`/task/${entry.task_id}`}>
                  {entry.description}
                </Link>
              ) : (
                <span className="account-usage__what">{entry.description}</span>
              )}
              {statusLabel[entry.status] ? (
                <span className="account-usage__status">{statusLabel[entry.status]}</span>
              ) : null}
              {/*
                One figure: what the balance did. A 预扣 still running shows in
                full, a run that produced nothing shows -0 rather than a bare
                nought, and a finished one shows what it actually took. Purchases
                and grants are the same column with the other sign.
              */}
              <span className="account-usage__amount">
                {entry.amount > 0 ? "+" : "-"}
                {Math.abs(entry.amount).toLocaleString()}
              </span>
            </li>
          ))}
        </ul>
      )}
      {hasMore ? (
        <button className="button button--quiet" type="button" disabled={busy} onClick={() => void loadMore()}>
          {text.loadMore}
        </button>
      ) : null}
    </section>
  );
}

export const AccountIcon = CreditCard;
