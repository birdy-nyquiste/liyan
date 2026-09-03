import {
  PROVIDER_TIMEOUT,
  SOURCE_BODY,
  expect,
  openWorkbench,
  openedTask,
  railLink,
  test,
} from "./support/workbench";

/**
 * 确认主题, and the 主题知言报告 it produces.
 *
 * The step sits between capturing 来源 and creating the task, and it is optional
 * — so both halves are walked here: a task confirmed with a 主题 gets a second
 * report and a gate that waits for it, and a task confirmed without one gets
 * neither. 提炼主题 is hidden, so typing is the only way in, and this asserts the
 * assistant is nowhere on the pane.
 */

function unique(): string {
  return `工时来源 ${Date.now().toString(36)}`;
}

/**
 * The 知言 area's own tab strip.
 *
 * Scoped rather than matched by text: the task also has a 来源 · 主题 workspace
 * switcher, while this tab list changes which report is being read.
 */
function reportTabs(card: ReturnType<typeof openedTask>) {
  return card.getByRole("tablist", { name: "知言报告" });
}

async function addPastedSource(page: import("@playwright/test").Page, title: string) {
  await railLink(page, "新建任务").click();
  await page.getByRole("button", { name: "添加来源" }).click();
  await page.getByLabel("来源标题").fill(title);
  await page.getByLabel("来源正文").fill(SOURCE_BODY);
  await page.getByLabel("出处（可选）").fill("https://press.example/four-day-week");
  await page.getByRole("button", { name: "添加来源" }).click();
  await expect(page.getByText("已就绪", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "下一步：确定主题" }).click();
}

test("写下的主题随任务一起确认并生成主题知言报告", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await addPastedSource(page, title);

  // 提炼主题 is not offered: no button, no region, nothing to press.
  await expect(page.getByRole("button", { name: /提炼主题/ })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "提炼主题" })).toHaveCount(0);

  // Unique, because the card is found by the 主题 it was confirmed with and
  // another spec in this file confirms one of its own.
  const theme = `四天工作制的实际代价 ${title}`;
  const box = page.getByRole("textbox", { name: "主题", exact: true });
  await box.fill(theme);
  await expect(box).toHaveValue(theme);

  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, theme);
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "知言 · 立言" }).click();

  // 主题 is listed first in the 知言 area, and its report is the one that says
  // what the 来源 leave out.
  const themeTab = reportTabs(card).getByRole("tab").first();
  await expect(themeTab).toBeVisible();
  await themeTab.click();
  await expect(
    card.getByRole("article", { name: /主题知言报告/ }),
  ).toBeVisible({ timeout: PROVIDER_TIMEOUT });
  await card.getByRole("button", { name: "来源之外的角度" }).click();
  await expect(card.getByText(/来源.*未提及|来源.*只引用/).first()).toBeVisible();

  // The gate counts it: 立言 opened only once both reports were in.
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });

  // A long 主题 and a short 来源 still hand their report body the same starting
  // line. Switching tabs must not make the prose jump vertically.
  const themeMeta = await card.getByRole("tabpanel").locator(".form-hint").first().boundingBox();
  await reportTabs(card).getByRole("tab").nth(1).click();
  const sourceMeta = await card.getByRole("tabpanel").locator(".form-hint").first().boundingBox();
  expect(themeMeta).not.toBeNull();
  expect(sourceMeta).not.toBeNull();
  expect(Math.abs(sourceMeta!.y - themeMeta!.y)).toBeLessThanOrEqual(1);
});

test("留空主题也能创建任务，且知言区没有主题一项", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await addPastedSource(page, title);

  // Nothing pressed, nothing typed: an empty 主题 is a complete answer.
  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, title);
  await card.getByRole("button", { name: "知言 · 立言" }).click();
  await expect(card.getByRole("article", { name: `知言报告 ${title}` })).toBeVisible({
    timeout: PROVIDER_TIMEOUT,
  });
  await expect(reportTabs(card).getByRole("tab")).toHaveCount(1);
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });
});

test("主题可以在编辑来源时改写与清空", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await addPastedSource(page, title);
  await page.getByRole("textbox", { name: "主题", exact: true }).fill("四天工作制的实际代价");
  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, "四天工作制的实际代价");
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "知言 · 立言" }).click();
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });

  await card.getByRole("button", { name: "来源 · 主题" }).click();
  await card.getByRole("button", { name: "编辑", exact: true }).click();
  const themeField = card.getByLabel("主题", { exact: true });
  await expect(themeField).toHaveValue("四天工作制的实际代价");

  // Clearing it is a save like any other, and it takes the 主题 report with it.
  await themeField.fill("");
  await card.getByRole("button", { name: /保存修改/ }).click();
  // Wait for the save to have landed before reading the 知言 area. Leaving the
  // pane while it is in flight is a thing a writer may do — and the product now
  // survives it — but a test that asserts the state *after* a save has to wait
  // for the save, or it is asserting on whichever arrived first.
  // The read-only 主题 pane saying 可留空 is the save having landed *and* the
  // thing this test is about: this version has no 主题 now.
  await expect(
    card.locator(".source-theme-pane").nth(1)
      .locator(".task-pane-heading").getByText("可留空", { exact: true }),
  ).toBeVisible();
  await card.getByRole("button", { name: "知言 · 立言" }).click();
  // One tab left: the 主题 that was cleared is gone, and so is its report.
  await expect(reportTabs(card).getByRole("tab")).toHaveCount(1);
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });
});
