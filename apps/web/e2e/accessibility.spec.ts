import { createTaskWithReport, expect, openWorkbench, test } from "./support/workbench";

/**
 * The accessibility checks that need a real browser.
 *
 * The Vitest suite in `src/components/accessibility.test.tsx` covers what jsdom
 * can see — accessible descriptions, focus, roles. Two things it cannot see are
 * here: what happens at a breakpoint, and whether a tab through the real page
 * ever leaves the visible viewport.
 *
 * `docs/operations/accessibility.md` holds the thresholds these are drawn from.
 */

const unique = () => `响应式 ${Date.now().toString(36)}`;

const BREAKPOINTS = [
  { name: "phone", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "laptop", width: 1280, height: 800 },
];

for (const breakpoint of BREAKPOINTS) {
  test(`the workbench fits ${breakpoint.name} without sideways scrolling`, async ({ page }) => {
    await page.setViewportSize({ width: breakpoint.width, height: breakpoint.height });
    await openWorkbench(page);
    // With a task open, because that is where the wide content is: a 知言报告
    // is dense lists and long quotes, and an empty workspace proves nothing
    // about either.
    await createTaskWithReport(page, unique());

    // A page wider than its viewport is the failure this catches: a fixed
    // width, an unwrapped row, a table nobody gave an overflow rule to.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `${breakpoint.name} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(1);
  });
}

test("every control a keyboard reaches is visible when it has focus", async ({ page }) => {
  await openWorkbench(page);
  await createTaskWithReport(page, unique());

  // A short timeout on purpose: this asks where focus is *now*, and the answer
  // never arrives late. The default would turn one off-screen control into a
  // twenty-second wait, twenty-five times over.
  const NOW = { timeout: 1_000 };
  const reached = new Set<string>();
  for (let presses = 0; presses < 25; presses += 1) {
    await page.keyboard.press("Tab");
    const focused = page.locator(":focus");
    if ((await focused.count()) === 0) continue;
    const tag = await focused.evaluate((element) => element.tagName);
    // Focus falls back to <body> when Tab moved nothing, so counting it would
    // let a trapped or empty tab order pass as twenty-five happy presses.
    if (tag === "BODY") continue;
    reached.add(`${presses}:${tag}`);
    // Focus that lands off-screen is focus a sighted keyboard user loses: the
    // page appears to stop responding while the caret is somewhere below it.
    await expect(focused, `focus left the viewport after ${presses + 1} tabs`).toBeInViewport(
      NOW,
    );
  }

  // An open 任务详情 has far more than this; the floor only has to be high
  // enough that a tab order which stopped moving cannot satisfy it.
  expect(reached.size, "Tab reached almost nothing, so this proved nothing.").toBeGreaterThan(5);
});
