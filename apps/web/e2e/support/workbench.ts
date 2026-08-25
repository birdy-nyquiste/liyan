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

/**
 * Put a signed-in writer in front of the workbench.
 *
 * Locally there is no Supabase project to sign in to, so the session Supabase
 * would have written is written directly: the server this run talks to resolves
 * any bearer token to one allowlisted writer, and the browser only has to be
 * holding one. Against Staging the real thing happens, with a code from a
 * Supabase test address rather than from a mailbox nothing here can read.
 */
export async function signIn(page: Page): Promise<void> {
  if (!AGAINST_STAGING) {
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
    await expect(page.getByRole("button", { name: "新建立言任务" })).toBeVisible();
    return;
  }

  expect(email, "Set LIYAN_E2E_EMAIL to an allowlisted Staging address.").not.toEqual("");
  expect(otp, "Set LIYAN_E2E_OTP to the code Supabase issues that address.").not.toEqual("");
  await page.goto("/");
  await page.getByLabel("邮箱").fill(email);
  await page.getByRole("button", { name: "发送验证码" }).click();
  await page.getByLabel("验证码").fill(otp);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("button", { name: "新建立言任务" })).toBeVisible();
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
  await page.getByRole("button", { name: "新建立言任务" }).click();
  await page.getByLabel("来源标题").fill(title);
  await page.getByLabel("来源正文").fill(SOURCE_BODY);
  await page.getByLabel("出处（可选）").fill("https://press.example/four-day-week");
  await page.getByRole("button", { name: "添加来源" }).click();
  await expect(page.getByText("已就绪", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "确认并创建任务" }).click();

  // A confirmed 立言任务 opens itself: the user just told the product what they
  // want to work on, and asking them to click it again would be a second ask.
  const card = openedTask(page, title);
  await expect(card).toBeVisible();
  await expect(card.getByRole("button", { name: /知言.*已完成/ })).toBeVisible({
    timeout: 90_000,
  });
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
  await card.getByRole("button", { name: /^立言/ }).click();
  await expect(card.getByRole("button", { name: "生成立言" })).toBeEnabled({
    timeout: 90_000,
  });
}

export const test = base;
export { expect };
