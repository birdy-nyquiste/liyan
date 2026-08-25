import {
  AGAINST_STAGING,
  createTaskWithReport,
  expect,
  openLiyan,
  openedTask,
  openWorkbench,
  PROVIDER_TIMEOUT,
  test,
} from "./support/workbench";

/**
 * The journeys the release gate requires a browser to prove.
 *
 * The server suite proves each rule through the API. What it cannot prove is
 * that a person can reach any of it: that the button exists, that it is
 * enabled at the right moment, that the answer arrives on screen. That is what
 * these are for, and it is why they assert on what a user sees rather than on
 * what was sent.
 */

const unique = () => `四天工作制 ${Date.now().toString(36)}`;

test("the sign-in screen asks for an address before anything else", async ({ browser }) => {
  // Signed out on purpose — every other spec arrives with the session the setup
  // step signed in. Whatever else is wrong, an unauthenticated visitor must
  // land somewhere that tells them what to do.
  const page = await browser.newPage({ storageState: undefined });
  await page.goto("/");

  await expect(page.getByLabel("邮箱")).toBeVisible();
  await expect(page.getByRole("button", { name: "发送验证码" })).toBeVisible();
  await page.close();
});

test("a pasted 来源 becomes a 立言任务 with a 知言报告", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);

  await createTaskWithReport(page, title);

  const card = openedTask(page, title);
  await expect(card.getByRole("article", { name: `知言报告 ${title}` })).toBeVisible();
  await expect(card.getByRole("heading", { name: "“知”事实" })).toBeVisible();
});

test("a 知言报告 is immutable once it succeeds", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  // No way back: a successful report has no start, retry, or cancel control.
  const card = openedTask(page, title);
  await expect(card.getByText("成功的知言报告不可编辑或重新生成。")).toBeVisible();
  await expect(card.getByRole("button", { name: "重试" })).toHaveCount(0);
  await expect(card.getByRole("button", { name: "终止分析" })).toHaveCount(0);
});

test("an article is generated, edited, saved, and restored", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  await openLiyan(page, title);
  await page.getByRole("button", { name: "生成立言" }).click();
  const editor = page.getByRole("textbox", { name: "文章正文" });
  await expect(editor).toBeVisible({ timeout: PROVIDER_TIMEOUT });

  await page.getByRole("button", { name: "保存 Revision" }).click();
  await expect(page.getByText("Revision 1", { exact: true })).toBeVisible();

  await editor.click();
  await page.keyboard.type("这一句是保存之后加的。");
  await page.getByRole("button", { name: "保存 Revision" }).click();
  await expect(page.getByText("Revision 2", { exact: true })).toBeVisible();

  // Restoring never rewinds: it creates Revision 3 carrying Revision 1's text,
  // so the history a user published from stays exactly as it was.
  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "恢复为当前 Revision" }).first().click();
  await expect(page.getByText("（由历史 Revision 恢复）")).toBeVisible();
});

test("a 立言任务 is deleted and leaves the list", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  page.once("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: `删除 ${title}` }).click();

  await expect(page.getByRole("button", { name: `打开 ${title}` })).toHaveCount(0);
});

test("publishing a saved Revision returns a Preview URL", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await createTaskWithReport(page, title);
  await openLiyan(page, title);
  await page.getByRole("button", { name: "生成立言" }).click();
  await expect(page.getByRole("textbox", { name: "文章正文" })).toBeVisible({
    timeout: PROVIDER_TIMEOUT,
  });
  await page.getByRole("button", { name: "保存 Revision" }).click();

  // Exact, and inside the task: 发布中心 is also a button whose name starts 发布.
  await openedTask(page, title).getByRole("button", { name: "发布", exact: true }).click();
  await page.getByLabel("作者（显示在 Blog 上）").fill("Zeng Zong");
  await page.getByRole("button", { name: "确认发布" }).click();

  await expect(page.getByRole("link", { name: /\/preview\// })).toBeVisible({ timeout: PROVIDER_TIMEOUT });
});

test("an unconfirmed Blog answer is shown as 结果未知 and cannot be resent", async ({
  page,
}) => {
  test.skip(
    AGAINST_STAGING,
    "Staging cannot be asked for an ambiguous Blog answer; ADR-0001 makes it terminal.",
  );
  const title = `结果未知 ${Date.now().toString(36)}`;
  await openWorkbench(page);
  await createTaskWithReport(page, title);
  await openLiyan(page, title);
  await page.getByRole("button", { name: "生成立言" }).click();
  await expect(page.getByRole("textbox", { name: "文章正文" })).toBeVisible({
    timeout: PROVIDER_TIMEOUT,
  });

  // The e2e Blog answers by title: this one asks for the outcome 立言阁 cannot
  // confirm, which is the case a user must never be invited to retry.
  const heading = page.getByRole("textbox", { name: "文章标题" });
  await heading.fill(title);
  await page.getByRole("button", { name: "保存 Revision" }).click();
  await openedTask(page, title).getByRole("button", { name: "发布", exact: true }).click();
  await page.getByLabel("作者（显示在 Blog 上）").fill("Zeng Zong");
  await page.getByRole("button", { name: "确认发布" }).click();

  await expect(page.getByText(/结果未知，立言阁不会重发/)).toBeVisible({ timeout: PROVIDER_TIMEOUT });
  // The refusal that matters: nothing offers to send it again.
  await expect(page.getByRole("button", { name: "重试本次提交" })).toHaveCount(0);
});

test("a URL 来源 that cannot be reached fails with a reason, not a spinner", async ({
  page,
}) => {
  test.skip(!AGAINST_STAGING, "A local run has no Chromium behind the worker to fetch with.");
  await openWorkbench(page);

  await page.getByRole("button", { name: "新建立言任务" }).click();
  await page.getByRole("button", { name: "公共文章链接" }).click();
  await page.getByLabel("来源网址").fill("https://example.invalid/does-not-resolve");
  await page.getByRole("button", { name: "添加来源" }).click();

  await expect(page.getByText(/无法|失败/).first()).toBeVisible({ timeout: PROVIDER_TIMEOUT });
});
