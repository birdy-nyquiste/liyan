import { resolve } from "node:path";

import {
  createTaskWithReport,
  expect,
  openLiyan,
  openWorkbench,
  openedTask,
  PROVIDER_TIMEOUT,
  railLink,
  test,
} from "./support/workbench";

/**
 * Where a capture from this run goes.
 *
 * Not `docs/design/`. The two `*-implementation.png` files there are the closed
 * record of the issue #23 sign-off — `workbench-design-qa.md` cites one of them
 * as the post-fix evidence its comparison history turns on — and writing them
 * from here overwrote that record with whatever the interface happened to look
 * like on the machine running the suite. A screenshot's bytes differ between
 * machines even when nothing about the design moved, so it also left every
 * local run with two PNGs in `git status` that no change had asked for.
 *
 * These captures are for looking at while working on the layout the assertions
 * above them check. `test-results/` is where the run's other evidence already
 * lands, and it is ignored.
 */
const capture = (name: string) => resolve(process.cwd(), "test-results/design", name);

test.use({ viewport: { width: 1440, height: 640 } });

test("the task creation page advances through a responsive source-to-theme pipeline", async ({ page }) => {
  await openWorkbench(page);
  await railLink(page, "新建任务").click();

  const session = page.getByRole("region", { name: "任务创建会话" });
  const panes = session.locator(".creation-pane");
  await expect(panes).toHaveCount(1);
  await expect(session.getByRole("heading", { name: "来源", exact: true })).toBeVisible();
  await expect(session.getByText("0/3", { exact: true })).toBeVisible();
  await expect(session.getByRole("textbox", { name: "主题", exact: true })).toHaveCount(0);
  const pipeline = session.locator(".creation-pipeline li");
  await expect(pipeline).toHaveCount(2);
  await expect(pipeline.nth(0)).toHaveAttribute("data-state", "current");
  await expect(pipeline.nth(1)).toHaveAttribute("data-state", "locked");
  const sessionChrome = await session.evaluate((element) => {
    const style = getComputedStyle(element);
    return { borderTopWidth: style.borderTopWidth, minHeight: style.minHeight };
  });
  expect(sessionChrome).toEqual({ borderTopWidth: "1px", minHeight: "0px" });

  await session.getByRole("button", { name: "添加来源" }).click();
  await expect(session.getByRole("button", { name: "粘贴文本" })).toBeVisible();
  await expect(session.getByLabel("来源标题")).toBeVisible();
  await expect(session.getByRole("button", { name: "创建任务" })).toHaveCount(0);
  await expect(session.getByRole("button", { name: "下一步：确定主题" })).toBeDisabled();

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(mobileOverflow).toBeLessThanOrEqual(0);
  const kindButtons = session.locator(".source-kind-tabs .button");
  const kindBoxes = await kindButtons.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect()),
  );
  expect(kindBoxes[1]!.top).toBeGreaterThanOrEqual(kindBoxes[0]!.bottom - 1);
});

test("the publication center advances through a responsive publish pipeline", async ({ page }) => {
  const title = `发布页面视觉校验 ${Date.now().toString(36)}`;
  await openWorkbench(page);
  await createTaskWithReport(page, title);
  await openLiyan(page, title);
  await page.getByRole("button", { name: "默认生成" }).click();
  await expect(page.getByRole("textbox", { name: "文章正文" })).toBeVisible({
    timeout: PROVIDER_TIMEOUT,
  });
  await page.getByRole("button", { name: "保存草稿" }).click();
  await openedTask(page, title).getByRole("button", { name: "发布", exact: true }).click();

  await expect(page.locator(".publication-flow")).toHaveCount(1);
  await expect(page.locator(".publication-history-section")).toHaveCount(1);
  const pipeline = page.locator(".publication-pipeline");
  const steps = pipeline.locator("li");
  await expect(steps).toHaveCount(2);
  await expect(steps.nth(0)).toHaveAttribute("data-state", "complete");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "current");
  const stepWidths = await steps.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().width),
  );
  expect(stepWidths[0]).toBeCloseTo(stepWidths[1]!, 0);

  const stage = page.locator(".publication-stage");
  await expect(stage).toHaveCount(1);
  await expect(stage.getByLabel("作者（显示在 Blog 上）")).toBeVisible();
  await expect(stage.getByRole("button", { name: "更换草稿" })).toBeVisible();
  const preview = stage.locator(".publication-article-preview");
  await expect(preview).toBeVisible();
  const previewStyle = await preview.evaluate((element) => {
    const style = getComputedStyle(element);
    return { maxHeight: style.maxHeight, overflowY: style.overflowY };
  });
  expect(previewStyle).toEqual({ maxHeight: "320px", overflowY: "auto" });

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(mobileOverflow).toBeLessThanOrEqual(0);
  await expect(page.locator("#publication-confirmation-heading")).toBeInViewport();

  await stage.getByRole("button", { name: "更换草稿" }).click();
  await expect(steps.nth(0)).toHaveAttribute("data-state", "current");
  await expect(steps.nth(1)).toHaveAttribute("data-state", "locked");
  await expect(page.locator("#publication-drafts-heading")).toBeVisible();
  await expect(page.locator("#publication-confirmation-heading")).toHaveCount(0);
});

test("the desktop task workspace preserves the approved two-pane composition", async ({ page }) => {
  const title = `当人的作品与产出均可被算法复制，人类独特的价值、尊严与生存分配如何摆脱产出逻辑另行安放 ${Date.now().toString(36)}`;
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  const task = openedTask(page, title);
  await task.getByRole("button", { name: "来源 · 主题" }).click();
  await expect(task.locator(".task-workspace-switcher li")).toHaveCount(2);
  const switcherGeometry = await task.locator(".task-workspace-switcher").evaluate((element) => {
    const track = element.querySelector("ol")?.getBoundingClientRect();
    const buttons = Array.from(element.querySelectorAll("button"), (button) => button.getBoundingClientRect());
    if (!track || buttons.length !== 2) throw new Error("Two workspace tabs must be present");
    return {
      trackLeft: track.left,
      switcherLeft: element.getBoundingClientRect().left,
      trackWidth: track.width,
      buttonWidths: buttons.map((button) => button.width),
    };
  });
  expect(switcherGeometry.trackLeft).toBeCloseTo(switcherGeometry.switcherLeft, 0);
  expect(switcherGeometry.trackWidth).toBeLessThanOrEqual(360);
  expect(switcherGeometry.buttonWidths[0]).toBeCloseTo(switcherGeometry.buttonWidths[1]!, 0);
  await expect(task.locator(".source-toolbar")).toHaveCount(0);
  const sourceThemePanes = task.locator(".source-theme-pane");
  await expect(sourceThemePanes).toHaveCount(2);
  const sourceHeader = sourceThemePanes.nth(0).locator(".task-pane-heading");
  await expect(sourceHeader.getByRole("heading", { name: "来源", exact: true })).toHaveCount(1);
  await expect(sourceHeader.getByText("1 个来源")).toBeVisible();
  await expect(sourceHeader.getByRole("combobox", { name: "版本" })).toHaveCount(0);
  const sourceTools = sourceThemePanes.nth(0).locator(".source-pane-tools");
  await expect(sourceTools.getByRole("combobox", { name: "版本" })).toBeVisible();
  await expect(sourceTools.getByRole("button", { name: "编辑" })).toBeVisible();
  const sourceThemeWidths = await sourceThemePanes.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().width),
  );
  const sourcesShare = sourceThemeWidths[0]! / (sourceThemeWidths[0]! + sourceThemeWidths[1]!);
  expect(sourcesShare).toBeGreaterThan(0.41);
  expect(sourcesShare).toBeLessThan(0.47);
  const sourceHeadingHeights = await sourceThemePanes.locator(".task-pane-heading").evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().height),
  );
  expect(sourceHeadingHeights[0]).toBeCloseTo(sourceHeadingHeights[1]!, 0);
  const sourcePaneGeometry = await sourceThemePanes.evaluateAll((elements) =>
    elements.map((element) => {
      const pane = element.getBoundingClientRect();
      const heading = element.querySelector(".task-pane-heading")?.getBoundingClientRect();
      if (!heading) throw new Error("Every source workspace pane needs a heading");
      return { left: pane.left, width: pane.width, headingTop: heading.top, headingBottom: heading.bottom };
    }),
  );
  const sourceScrollbarGutters = await sourceThemePanes.locator(".source-theme-pane__body").evaluateAll((elements) =>
    elements.map((element) => getComputedStyle(element).scrollbarGutter),
  );
  expect(sourceScrollbarGutters).toEqual(["stable", "stable"]);

  const taskTitle = task.locator(".task-card__identity > h3");
  const titleStyle = await taskTitle.evaluate((element) => {
    const style = getComputedStyle(element);
    return { overflow: style.overflow, textOverflow: style.textOverflow, whiteSpace: style.whiteSpace };
  });
  expect(titleStyle).toEqual({ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" });
  const sublineItems = task.locator(".task-card__subline > .task-card__meta, .task-card__subline > .task-card__actions");
  const sublineBoxes = await sublineItems.evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { centerY: rect.y + rect.height / 2 };
    }),
  );
  expect(sublineBoxes[0]!.centerY).toBeCloseTo(sublineBoxes[1]!.centerY, 0);

  await task.getByRole("button", { name: "知言 · 立言" }).click();
  await expect(task.locator(".zhiyan-tab__title")).toHaveText(["来源 #1"]);
  const panes = task.locator(".task-workspace-pane");
  await expect(panes).toHaveCount(2);
  const workspaceHeadingHeights = await panes.locator(".task-pane-heading").evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().height),
  );
  expect(workspaceHeadingHeights[0]).toBeCloseTo(sourceHeadingHeights[0]!, 0);
  expect(workspaceHeadingHeights[1]).toBeCloseTo(sourceHeadingHeights[0]!, 0);
  const widths = await panes.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect().width),
  );
  expect(widths[0]! / (widths[0]! + widths[1]!)).toBeGreaterThan(0.41);
  expect(widths[0]! / (widths[0]! + widths[1]!)).toBeLessThan(0.47);
  const workPaneGeometry = await panes.evaluateAll((elements) =>
    elements.map((element) => {
      const pane = element.getBoundingClientRect();
      const heading = element.querySelector(".task-pane-heading")?.getBoundingClientRect();
      if (!heading) throw new Error("Every writing workspace pane needs a heading");
      return { left: pane.left, width: pane.width, headingTop: heading.top, headingBottom: heading.bottom };
    }),
  );
  for (const index of [0, 1]) {
    expect(workPaneGeometry[index]!.left).toBeCloseTo(sourcePaneGeometry[index]!.left, 0);
    expect(workPaneGeometry[index]!.width).toBeCloseTo(sourcePaneGeometry[index]!.width, 0);
    expect(workPaneGeometry[index]!.headingTop).toBeCloseTo(sourcePaneGeometry[index]!.headingTop, 0);
    expect(workPaneGeometry[index]!.headingBottom).toBeCloseTo(sourcePaneGeometry[index]!.headingBottom, 0);
  }

  const reportPanel = task.getByRole("tabpanel");
  const composer = task.locator(".liyan-composer");
  await expect(composer).toBeVisible();
  const composerBefore = await composer.boundingBox();
  await reportPanel.getByRole("button", { name: "概要" }).click();
  await expect(composer).toBeVisible();
  const composerAfter = await composer.boundingBox();
  expect(composerBefore).not.toBeNull();
  expect(composerAfter).not.toBeNull();
  expect(composerAfter!.y).toBeCloseTo(composerBefore!.y, 0);
  const reportScroll = await reportPanel.evaluate((element) => {
    element.scrollTop = 80;
    return {
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      scrollTop: element.scrollTop,
    };
  });
  expect(reportScroll.scrollHeight).toBeGreaterThan(reportScroll.clientHeight);
  expect(reportScroll.scrollTop).toBeGreaterThan(0);

  const shellMotion = await page.locator(".app-frame").evaluate((element) => {
    const frameStyle = getComputedStyle(element);
    const sidebar = document.querySelector(".desktop-sidebar");
    if (!(sidebar instanceof HTMLElement)) throw new Error("Desktop sidebar must be present");
    const sidebarStyle = getComputedStyle(sidebar);
    return {
      frameProperty: frameStyle.transitionProperty,
      frameDuration: frameStyle.transitionDuration,
      sidebarProperty: sidebarStyle.transitionProperty,
      sidebarDuration: sidebarStyle.transitionDuration,
    };
  });
  expect(shellMotion.frameProperty).toContain("padding-left");
  expect(shellMotion.frameDuration).not.toBe("0s");
  expect(shellMotion.sidebarProperty).toContain("width");
  expect(shellMotion.sidebarDuration).not.toBe("0s");

  const frame = page.locator(".app-frame");
  const collapseButton = page.locator(".desktop-sidebar .sidebar-collapse");
  if (await frame.getAttribute("data-sidebar-collapsed")) {
    await collapseButton.click();
    await page.waitForTimeout(350);
  }
  const persistentIcons = page.locator(
    ".desktop-sidebar .sidebar-nav-link > svg:first-child, .desktop-sidebar .sidebar-identity .avatar",
  );
  const expandedIconGeometry = await persistentIcons.evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    }),
  );
  const accountAlignment = await page.locator(".desktop-sidebar .sidebar-identity").evaluate((element) => {
    const avatar = element.querySelector(".avatar")?.getBoundingClientRect();
    const email = element.querySelector(".sidebar-identity__email")?.getBoundingClientRect();
    if (!avatar || !email) throw new Error("Account identity must include avatar and email");
    return {
      avatarCenter: avatar.y + avatar.height / 2,
      emailCenter: email.y + email.height / 2,
    };
  });
  expect(accountAlignment.avatarCenter).toBeCloseTo(accountAlignment.emailCenter, 0);
  const accountTextStarts = await page.locator(".desktop-sidebar").evaluate((sidebar) => {
    const setting = sidebar.querySelector(".sidebar-account__action > span:not(.sidebar-account__value)")?.getBoundingClientRect();
    const email = sidebar.querySelector(".sidebar-identity__email")?.getBoundingClientRect();
    if (!setting || !email) throw new Error("Sidebar account text columns must be present");
    return { setting: setting.x, email: email.x };
  });
  expect(accountTextStarts.setting).toBeCloseTo(accountTextStarts.email, 0);
  await collapseButton.click();
  await page.waitForTimeout(350);
  const collapsedIconGeometry = await persistentIcons.evaluateAll((elements) =>
    elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
    }),
  );
  expect(collapsedIconGeometry).toEqual(expandedIconGeometry);
  await expect(page.locator(".desktop-sidebar .sidebar-nav-link > span")).toHaveCount(3);
  await page.locator(".desktop-sidebar .sidebar-section-toggle").click();
  await page.waitForTimeout(350);
  await expect(frame).not.toHaveAttribute("data-sidebar-collapsed");
  await expect(page.locator(".desktop-sidebar .sidebar-task-list")).toBeVisible();

  await page.setViewportSize({ width: 900, height: 640 });
  const geometry = await task.evaluate((element) => {
    const header = element.querySelector(":scope > .task-card__content");
    const detail = element.querySelector(":scope > .task-detail");
    if (!(header instanceof HTMLElement) || !(detail instanceof HTMLElement)) {
      throw new Error("Opened task header and detail must be present");
    }
    return {
      headerHeight: header.getBoundingClientRect().height,
      headerBottom: header.getBoundingClientRect().bottom,
      detailTop: detail.getBoundingClientRect().top,
    };
  });
  expect(geometry.headerHeight).toBeGreaterThan(96);
  expect(geometry.detailTop).toBeGreaterThanOrEqual(geometry.headerBottom - 1);

  await page.setViewportSize({ width: 1440, height: 640 });
  await page.screenshot({
    path: capture("workbench-implementation.png"),
  });
});

test("the mobile task workspace stacks without clipping its active stage", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const title = `移动端长标题校验：人的价值如何摆脱产出逻辑 ${Date.now().toString(36)}`;
  await openWorkbench(page);
  await createTaskWithReport(page, title);

  const task = openedTask(page, title);
  await task.getByRole("button", { name: "来源 · 主题" }).click();
  const sourceThemePanes = task.locator(".source-theme-pane");
  await expect(sourceThemePanes).toHaveCount(2);
  const sourceThemeBoxes = await sourceThemePanes.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect()),
  );
  expect(sourceThemeBoxes[1]!.top).toBeGreaterThanOrEqual(sourceThemeBoxes[0]!.bottom - 1);

  await task.getByRole("button", { name: "知言 · 立言" }).click();
  const zhiyanHeading = task.getByRole("heading", { name: "知言", exact: true });
  await expect(zhiyanHeading).toBeInViewport();
  const headingBox = await zhiyanHeading.boundingBox();
  expect(headingBox).not.toBeNull();
  expect(headingBox!.y).toBeGreaterThanOrEqual(60);
  await expect(task.getByRole("tablist", { name: "知言报告" })).toBeInViewport();
  const panes = task.locator(".task-workspace-pane");
  await expect(panes).toHaveCount(2);
  const boxes = await panes.evaluateAll((elements) =>
    elements.map((element) => element.getBoundingClientRect()),
  );
  expect(boxes[1]!.top).toBeGreaterThanOrEqual(boxes[0]!.bottom - 1);

  await page.screenshot({
    path: capture("workbench-mobile-implementation.png"),
  });
});
