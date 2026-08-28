import { useCallback, useEffect, useState } from "react";
import { CreditCard } from "lucide-react";

import {
  getAccount,
  listAccountUsage,
  type AccountResponse,
  type UsageEntry,
} from "../api/client";
import { useInterfaceLocale } from "../interfaceLocale";

const copy = {
  zh: {
    title: "账户",
    remaining: "剩余额度",
    unit: "额度",
    packs: "购买额度",
    packsSoon: "购买功能即将开放。",
    history: "使用记录",
    empty: "还没有使用记录",
    loadMore: "加载更多",
    failed: "账户信息加载失败，请稍后重试。",
    locked: "购买额度后可使用公共文章链接与上传文件作为来源。",
    spends: "消耗额度",
    spendsFree: "不消耗额度",
    spendCapture: "添加来源",
    spendZhiyan: "知言分析",
    spendLiyan: "立言生成（含每次重新生成）",
    freePublish: "发布",
    freeFailed: "失败的分析与生成",
    freeUnchanged: "重复分析未改动的来源",
    running: "进行中",
    done: "已完成",
    failedRun: "失败",
    held: "预扣",
    returned: "已结算",
  },
  en: {
    title: "Account",
    remaining: "Credits remaining",
    unit: "credits",
    packs: "Buy credits",
    packsSoon: "Buying is not open yet.",
    history: "Usage history",
    empty: "Nothing used yet",
    loadMore: "Load more",
    failed: "The account could not be loaded. Try again shortly.",
    locked: "Buying credits unlocks article links and uploaded files as sources.",
    spends: "Spends credits",
    spendsFree: "Free",
    spendCapture: "Adding a source",
    spendZhiyan: "知言 analysis",
    spendLiyan: "立言 generation, including every regeneration",
    freePublish: "Publishing",
    freeFailed: "Analyses and generations that failed",
    freeUnchanged: "Re-analysing an unchanged source",
    running: "Running",
    done: "Done",
    failedRun: "Failed",
    held: "Held",
    returned: "Settled",
  },
} as const;

/** What one 额度包 offers. Prices are USD; the 额度 are 立言阁's own arithmetic. */
const PACKS = [
  { price: "$5", credits: 2_000 },
  { price: "$20", credits: 8_000 },
  { price: "$50", credits: 20_000 },
] as const;

export function AccountPage({ accessToken }: { accessToken: string }): React.ReactElement {
  const { locale } = useInterfaceLocale();
  const text = copy[locale];
  const [account, setAccount] = useState<AccountResponse | null>(null);
  const [entries, setEntries] = useState<UsageEntry[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);

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
    } catch {
      setFailed(true);
    }
  }, [accessToken]);

  useEffect(() => {
    void load();
  }, [load]);

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
        What spends 额度, said here because nothing quotes a price before an act
        and 使用记录 only explains one afterwards. The second column matters as
        much as the first: a user who does not know a failed run is free will
        assume it was not.
      */}
      <div className="account-spending">
        <div>
          <h2>{text.spends}</h2>
          <ul>
            <li>{text.spendCapture}</li>
            <li>{text.spendZhiyan}</li>
            <li>{text.spendLiyan}</li>
          </ul>
        </div>
        <div>
          <h2>{text.spendsFree}</h2>
          <ul>
            <li>{text.freePublish}</li>
            <li>{text.freeFailed}</li>
            <li>{text.freeUnchanged}</li>
          </ul>
        </div>
      </div>

      <h2>{text.packs}</h2>
      <ul className="account-packs">
        {PACKS.map((pack) => (
          <li key={pack.price} className="account-pack">
            <span className="account-pack__price">{pack.price}</span>
            <span className="account-pack__credits">
              {pack.credits.toLocaleString()} {text.unit}
            </span>
          </li>
        ))}
      </ul>
      {!account?.is_paying_user ? (
        <p className="account-entitlement">{text.locked}</p>
      ) : null}
      <p className="account-packs__note">{text.packsSoon}</p>

      <h2>{text.history}</h2>
      {entries.length === 0 ? (
        <p className="account-empty">{text.empty}</p>
      ) : (
        <ul className="account-usage">
          {entries.map((entry) => (
            <li key={entry.id} className="account-usage__row">
              <span className="account-usage__what">{entry.description}</span>
              {statusLabel[entry.status] ? (
                <span className="account-usage__status">{statusLabel[entry.status]}</span>
              ) : null}
              <span className="account-usage__amount">
                {entry.amount > 0 ? "+" : ""}
                {entry.amount.toLocaleString()}
              </span>
              {/*
                The 预扣 beside the amount is the point of this row. A balance
                that moved and moved back, with nothing saying why, is the thing
                users write in about.
              */}
              {entry.held !== null && entry.held !== -entry.amount ? (
                <span className="account-usage__held">
                  {text.held} {entry.held} · {text.returned}
                </span>
              ) : null}
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
