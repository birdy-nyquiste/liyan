import { resolve } from "node:path";

import { createTaskWithReport, expect, openWorkbench, openedTask, test } from "./support/workbench";

test.use({ viewport: { width: 1440, height: 640 } });

test("the desktop task workspace preserves the approved two-pane composition", async ({ page }) => {
  const title = `视觉校验 ${Date.now().toString(36)}`;
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  const task = openedTask(page, title);
  await task.getByRole("tab", { name: "知言 · 立言" }).click();
  const panes = task.locator(".task-workspace-pane");
  await expect(panes).toHaveCount(2);
  const widths = await panes.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().width),
  );
  expect(widths[0]! / (widths[0]! + widths[1]!)).toBeGreaterThan(0.41);
  expect(widths[0]! / (widths[0]! + widths[1]!)).toBeLessThan(0.47);

  await page.screenshot({
    path: resolve(process.cwd(), "../../docs/design/workbench-implementation.png"),
  });
});
