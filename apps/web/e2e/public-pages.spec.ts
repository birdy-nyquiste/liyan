import { expect, test } from "./support/workbench";
import { mkdirSync } from "node:fs";

const captures = "../../.impeccable/review";

test("public pages preserve the entry flow, section navigation and display preferences", async ({ browser }) => {
  mkdirSync(captures, { recursive: true });
  const page = await browser.newPage({ storageState: undefined, viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("link", { name: "立即体验", exact: true }).first()).toBeVisible();
  await expect(page.getByLabel("邮箱", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("article", { name: "来源知言报告", exact: true }).getByRole("heading", { level: 5 })).toHaveCount(7);
  await expect(page.getByRole("article", { name: "主题知言报告", exact: true }).getByRole("heading", { level: 5 })).toHaveCount(6);
  await page.screenshot({ path: `${captures}/desktop.png`, fullPage: true });
  await page.getByRole("link", { name: "价格", exact: true }).click();
  await expect(page).toHaveURL(/#pricing$/);
  await expect(page.getByRole("heading", { name: "价格", exact: true })).toBeInViewport();
  await page.getByRole("link", { name: "常见问题", exact: true }).click();
  const question = "支持哪些来源？一个任务能放几个？";
  await expect(page.getByText(/一个任务最多 3 个来源/)).toBeHidden();
  await page.getByText(question, { exact: true }).click();
  await expect(page.getByText(/一个任务最多 3 个来源/)).toBeVisible();
  await page.getByRole("link", { name: "使用条款", exact: true }).click();
  await expect(page.getByRole("heading", { name: "使用条款", exact: true })).toBeVisible();
  await page.reload();
  // The reload is the point: a direct load of a routed path has to serve the
  // document, not the shell. Asserted on a chapter heading rather than on the
  // placeholder that used to stand here.
  await expect(page.getByRole("heading", { name: "四、你的内容", exact: true })).toBeVisible();
  // The footer's link: both documents cross-reference each other now, so the
  // page holds more than one route to 隐私政策 and only this one is navigation.
  await page.getByRole("navigation", { name: "法律与联系" })
    .getByRole("link", { name: "隐私政策", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "隐私政策", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "三、浏览器插件", exact: true })).toBeVisible();
  await expect(page.getByText(/Limited Use 要求/)).toBeVisible();
  await expect(page.getByRole("link", { name: "联系我们" })).toHaveAttribute("href", "mailto:birdyyao@nyquiste.com");
  await page.getByRole("link", { name: "立即体验", exact: true }).click();
  await expect(page).toHaveURL(/\/sign-in$/);
  await expect(page.getByLabel("邮箱", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${captures}/sign-in.png`, fullPage: true });
  await page.getByRole("link", { name: "立言阁首页", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("link", { name: "立即体验", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("heading", { name: "常见问题", exact: true })).toBeAttached();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({ path: `${captures}/mobile.png`, fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("button", { name: "模式: 浅色" }).click();
  await page.screenshot({ path: `${captures}/mobile-dark.png`, fullPage: true });
  await page.getByRole("button", { name: "语言: 中文" }).click();
  await expect(page.getByRole("link", { name: "Get started", exact: true }).first()).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.screenshot({ path: `${captures}/desktop-dark-english.png`, fullPage: true });
  expect(errors).toEqual([]);
  await page.close();
});

test("signed-in homepage CTAs enter the existing workbench", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "前往工作台", exact: true })).toHaveCount(4);
  await expect(page).toHaveURL(/\/$/);
  await page.getByRole("link", { name: "前往工作台", exact: true }).first().click();
  await expect(page).toHaveURL(/\/task$/);
  await expect(page.getByRole("heading", { name: "新建立言任务", exact: true })).toBeVisible();
});
