import { readFileSync } from "node:fs";

import { expect, type Page, test as base } from "@playwright/test";

/**
 * What the two runs have to agree on: how a writer gets in, and what a task
 * looks like once it exists.
 *
 * Everything below is written so a spec never has to know which run it is in.
 * The one thing that genuinely differs is sign-in — Staging has a Supabase
 * project and a mailbox, and a local run has neither — so it is the one thing
 * this module branches on.
 */

export const STAGING_URL = process.env.LIYAN_E2E_BASE_URL;
export const AGAINST_STAGING = Boolean(STAGING_URL);

/**
 * How long provider-paced work is given to finish.
 *
 * Against doubles this is instant. Against DeepSeek it is a 知言 run with Web
 * Search, which the server itself allows 300 seconds for
 * (`LIYAN_ZHIYAN_TIMEOUT_SECONDS`) — so waiting less than the server does would
 * fail the test for the run still being within its own budget.
 */
export const PROVIDER_TIMEOUT = AGAINST_STAGING ? 330_000 : 90_000;

/**
 * The project reference supabase-js derives from `VITE_SUPABASE_URL`, which is
 * the first label of its hostname — so this must match `.env.e2e`, and it is
 * written out rather than derived because this process never reads that file.
 *
 * Getting it wrong is loud rather than subtle: the seeded session is then
 * stored under a key nothing reads, and `signIn` fails on the very next line.
 */
const LOCAL_PROJECT_REF = "liyan-e2e";
const LOCAL_ACCESS_TOKEN = "allowed-token";

const email = process.env.LIYAN_E2E_EMAIL ?? "";
const otp = process.env.LIYAN_E2E_OTP ?? "";

/**
 * A body long enough that intake does not warn about it.
 *
 * A short 来源 is accepted with a warning the user must acknowledge, which is
 * its own journey and not the one most specs are walking.
 */
export const SOURCE_BODY =
  "英国2022年的四天工作制试验已经证明了显著效果，参与企业的营收、员工留存与健康指标都被反复引用。".repeat(
    16,
  );

/** Where the signed-in session is saved, and where every spec reads it from. */
export const SESSION_STATE = "e2e/.auth/session.json";

/**
 * Whether a session from an earlier run is still usable.
 *
 * Codes are scarce: each one Supabase issues invalidates the last, and asking
 * for a fresh one to re-run a failed spec means a person fetching mail. A
 * saved session outlives the code that produced it, so a run within its life
 * reuses it rather than spending another.
 */
export function storedSessionIsLive(): boolean {
  try {
    const state = JSON.parse(readFileSync(SESSION_STATE, "utf8")) as {
      origins?: { localStorage?: { name: string; value: string }[] }[];
    };
    const stored = state.origins
      ?.flatMap((origin) => origin.localStorage ?? [])
      .find((entry) => entry.name.endsWith("-auth-token"));
    if (!stored) return false;
    const session = JSON.parse(stored.value) as { expires_at?: number };
    // A minute of margin, so a session cannot expire between this and the
    // first request that would use it.
    return Boolean(session.expires_at && session.expires_at > Date.now() / 1000 + 60);
  } catch {
    return false;
  }
}

/**
 * Write the session Supabase would have written.
 *
 * A local run has no Supabase project to sign in to, and the server it talks to
 * resolves any bearer token to one allowlisted writer — so the browser only has
 * to be holding one.
 */
export async function seedLocalSession(page: Page): Promise<void> {
  await page.addInitScript(
    ([ref, token]) => {
      const oneDay = 24 * 60 * 60;
      window.localStorage.setItem(
        `sb-${ref}-auth-token`,
        JSON.stringify({
          access_token: token,
          token_type: "bearer",
          expires_in: oneDay,
          expires_at: Math.floor(Date.now() / 1000) + oneDay,
          refresh_token: `${token}-refresh`,
          user: {
            id: "00000000-0000-4000-8000-000000000001",
            aud: "authenticated",
            role: "authenticated",
            email: "writer@example.com",
          },
        }),
      );
    },
    [LOCAL_PROJECT_REF, LOCAL_ACCESS_TOKEN],
  );
  await page.goto("/");
  await expect(page.getByRole("link", { name: "新建立言任务" })).toBeVisible();
}

/**
 * The real thing: an address, a code, and a workspace on the other side.
 *
 * The code is spent by this, which is why it happens once per run in the setup
 * project rather than once per spec.
 */
export async function signInWithOtp(page: Page): Promise<void> {
  expect(email, "Set LIYAN_E2E_EMAIL to an allowlisted Staging address.").not.toEqual("");
  expect(otp, "Set LIYAN_E2E_OTP to a code Supabase issued that address.").not.toEqual("");
  await page.goto("/");
  await page.getByLabel("邮箱").fill(email);
  await page.getByRole("button", { name: "发送验证码" }).click();
  await page.getByLabel("验证码").fill(otp);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("link", { name: "新建立言任务" })).toBeVisible({
    timeout: 60_000,
  });
}

/**
 * Sign in against the real Supabase project without spending the code twice.
 *
 * The workbench's own form cannot be driven with a code somebody hands you:
 * reaching the 验证码 field means submitting the address, and submitting the
 * address makes Supabase issue a *new* code, silently invalidating the one you
 * were about to type. The form flow needs a fixed test OTP — an address
 * configured in Supabase to accept one unchanging code without sending mail —
 * and `signInWithOtp` above is what runs when `LIYAN_E2E_FIXED_OTP=1` says one
 * exists.
 *
 * Without that, this verifies the code against Supabase directly and writes the
 * session it returns. What that proves is narrower and worth naming: a real
 * Supabase project, a real code, a real session the workbench accepts — but not
 * the sign-in form itself. `docs/operations/release-gate.md` says so too.
 */
export async function bootstrapStagingSession(page: Page): Promise<void> {
  expect(email, "Set LIYAN_E2E_EMAIL to an allowlisted Staging address.").not.toEqual("");
  expect(otp, "Set LIYAN_E2E_OTP to a code Supabase issued that address.").not.toEqual("");
  const project = await stagingSupabaseProject(page);

  const verified = await page.request.post(`${project.url}/auth/v1/verify`, {
    headers: { apikey: project.key, "Content-Type": "application/json" },
    data: { type: "email", email, token: otp },
  });
  expect(
    verified.ok(),
    `Supabase refused the code (${verified.status()}). A newer code invalidates an older one.`,
  ).toBe(true);
  const session = await verified.json();

  const reference = new URL(project.url).hostname.split(".")[0];
  await page.addInitScript(
    ([ref, stored]) => window.localStorage.setItem(`sb-${ref}-auth-token`, stored),
    [reference, JSON.stringify(session)],
  );
}

/**
 * The Supabase project the deployed workbench is built against.
 *
 * Read from the bundle rather than from configuration here, because these two
 * values are public by construction — the browser receives both — and the one
 * thing that matters is that they are the deployment's own, not a developer's.
 */
async function stagingSupabaseProject(page: Page): Promise<{ url: string; key: string }> {
  const index = await (await page.request.get("/")).text();
  const bundle = /\/assets\/[^"']+\.js/.exec(index)?.[0];
  expect(bundle, "The workbench page named no bundle to read configuration from.").toBeTruthy();
  const script = await (await page.request.get(bundle!)).text();
  const url = /https:\/\/[a-z0-9]+\.supabase\.co/.exec(script)?.[0];
  const key = /sb_publishable_[A-Za-z0-9_-]+/.exec(script)?.[0];
  expect(url && key, "The deployed bundle carries no Supabase project.").toBeTruthy();
  return { url: url!, key: key! };
}

/** Whether Supabase is configured to accept one unchanging code for this address. */
export const FIXED_OTP = process.env.LIYAN_E2E_FIXED_OTP === "1";

/**
 * Open the workbench as the writer the setup step signed in.
 *
 * The session arrives with the browser context, so this only has to load the
 * page and check that it did — a storage state that has gone stale looks
 * exactly like a sign-in that never happened, and it must fail here rather
 * than three assertions later.
 */
export async function openWorkbench(page: Page): Promise<void> {
  await page.goto("/");
  const newTask = page.getByRole("link", { name: "新建立言任务" });
  if ((page.viewportSize()?.width ?? 1280) <= 800) {
    await page.getByRole("button", { name: "打开导航" }).click();
  }
  await expect(newTask).toBeVisible({
    timeout: 60_000,
  });
}

/**
 * Create one 立言任务 from one pasted 来源, and wait for its 知言报告.
 *
 * Most specs start after this point, and none of them should have to repeat it.
 * The title is made unique by the caller, because a Staging run leaves its
 * tasks behind and a suite that reuses one name becomes unreadable after the
 * second release.
 */
export async function createTaskWithReport(page: Page, title: string): Promise<void> {
  await page.getByRole("link", { name: "新建立言任务" }).click();
  await page.getByRole("button", { name: "添加来源" }).click();
  await page.getByLabel("来源标题").fill(title);
  await page.getByLabel("来源正文").fill(SOURCE_BODY);
  await page.getByLabel("出处（可选）").fill("https://press.example/four-day-week");
  await page.getByRole("button", { name: "添加来源" }).click();
  await expect(page.getByText("已就绪", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "创建任务" }).click();

  // A confirmed 立言任务 opens itself: the user just told the product what they
  // want to work on, and asking them to click it again would be a second ask.
  const card = openedTask(page, title);
  await expect(card).toBeVisible();
  // Both outcomes, not just the happy one. A 知言 run that fails — DeepSeek
  // answering `busy` is the common way — leaves a summary that will never say
  // 已完成, and waiting the full provider budget for it costs five minutes and
  // then reports a timeout, which reads like the product hung. The workbench
  // already tells these apart on screen, so this reads what it says.
  await card.getByRole("tab", { name: "知言 · 立言" }).click();
  const zhiyan = card.getByText(/份报告已完成|个来源分析失败/).first();
  await expect(zhiyan).toHaveText(/已完成|分析失败/, { timeout: PROVIDER_TIMEOUT });
  await expect(
    zhiyan,
    "知言 failed rather than timed out — the provider refused, which is not this test's subject.",
  ).not.toHaveText(/分析失败/);
}

/** The 任务详情 of one open 立言任务, which every later step works inside. */
export function openedTask(page: Page, title: string) {
  return page.getByRole("article", { name: `已打开任务 ${title}` });
}

/**
 * Expand 立言 and wait until it can be written.
 *
 * The three task areas are collapsible and only the expanded one renders, so
 * 立言's controls do not exist until this has happened — which is deliberate in
 * the product and a step every article spec has to take.
 */
export async function openLiyan(page: Page, title: string): Promise<void> {
  const card = openedTask(page, title);
  await card.getByRole("tab", { name: "知言 · 立言" }).click();
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });
}

export const test = base;
export { expect };
