import {
  PROVIDER_TIMEOUT,
  SOURCE_BODY,
  expect,
  openWorkbench,
  openedTask,
  test,
} from "./support/workbench";

/**
 * 确认主题, and the 主题知言报告 it produces.
 *
 * The step sits between capturing 来源 and creating the task, and it is optional
 * — so both halves are walked here: a task confirmed with a 主题 gets a second
 * report and a gate that waits for it, and the Agent's three candidates are an
 * offer the writer may take, edit, or ignore.
 */

function unique(): string {
  return `工时来源 ${Date.now().toString(36)}`;
}

/**
 * The 知言 area's own tab strip.
 *
 * Scoped rather than matched by text: the task's stage tabs are now
 * 来源 · 主题 and 知言 · 立言, so a bare `getByRole("tab")` filtered on 主题
 * finds the stage tab first — and clicking it navigates away from the reports.
 */
function reportTabs(card: ReturnType<typeof openedTask>) {
  return card.getByRole("tablist", { name: "知言报告" });
}

async function addPastedSource(page: import("@playwright/test").Page, title: string) {
  await page.getByRole("link", { name: "新建任务" }).click();
  await page.getByRole("button", { name: "添加来源" }).click();
  await page.getByLabel("来源标题").fill(title);
  await page.getByLabel("来源正文").fill(SOURCE_BODY);
  await page.getByLabel("出处（可选）").fill("https://press.example/four-day-week");
  await page.getByRole("button", { name: "添加来源" }).click();
  await expect(page.getByText("已就绪", { exact: true }).first()).toBeVisible();
}

test("三个候选可选可改，主题随任务一起确认并生成主题知言报告", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await addPastedSource(page, title);

  // The button is live only now that the 来源 is captured.
  const propose = page.getByRole("button", { name: /提炼主题/ });
  await expect(propose).toBeEnabled();
  await propose.click();

  // Three candidates, each with its own reason for fitting the material.
  const candidates = page.getByRole("list", { name: "主题候选" }).getByRole("listitem");
  await expect(candidates).toHaveCount(3, { timeout: PROVIDER_TIMEOUT });
  const chosen = (await candidates.first().getByRole("strong").textContent()) ?? "";
  await candidates.first().getByRole("button").click();

  // Pressing one fills the box, and the box stays the writer's to edit.
  const box = page.getByLabel("主题", { exact: true });
  await expect(box).toHaveValue(chosen);
  await box.fill(`${chosen}（我改过）`);

  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, `${chosen}（我改过）`);
  await expect(card).toBeVisible();
  await card.getByRole("tab", { name: "知言 · 立言" }).click();

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
});

test("留空主题也能创建任务，且知言区没有主题一项", async ({ page }) => {
  const title = unique();
  await openWorkbench(page);
  await addPastedSource(page, title);

  // Nothing pressed, nothing typed: an empty 主题 is a complete answer.
  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, title);
  await card.getByRole("tab", { name: "知言 · 立言" }).click();
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
  await page.getByLabel("主题", { exact: true }).fill("四天工作制的实际代价");
  await page.getByRole("button", { name: "创建任务" }).click();

  const card = openedTask(page, "四天工作制的实际代价");
  await expect(card).toBeVisible();
  await card.getByRole("tab", { name: "知言 · 立言" }).click();
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });

  await card.getByRole("tab", { name: "来源 · 主题" }).click();
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
  // The read-only 主题 card saying 未设置 is the save having landed *and* the
  // thing this test is about: this version has no 主题 now.
  await expect(card.getByText("未设置")).toBeVisible();
  await card.getByRole("tab", { name: "知言 · 立言" }).click();
  // One tab left: the 主题 that was cleared is gone, and so is its report.
  await expect(reportTabs(card).getByRole("tab")).toHaveCount(1);
  await expect(card.getByRole("button", { name: "默认生成" })).toBeEnabled({
    timeout: PROVIDER_TIMEOUT,
  });
});
