/**
 * Chrome Web Store listing screenshots, 1280x800, from the real panel.
 *
 * The panel is 360px wide and a listing image is 1280x800, so each shot is the
 * real popup presented over a stand-in for the page being read — which is what
 * the extension actually looks like in use. No marketing copy is added: the
 * words on the listing belong to the author, not to this script.
 *
 * Needs both of these already running:
 *   .venv/bin/python scripts/e2e_server.py --port 8099   (with a purchase seeded)
 *   cd apps/extension && npx vite --mode e2e --port 5199
 */
import { chromium } from "@playwright/test";
import { mkdirSync } from "node:fs";

const HARNESS = "http://localhost:5199/harness.html";
const OUT = process.argv[2] ?? "./shots";

/** Three distinct URLs, so the basket holds three rows. */
const PAGES = [
  ["https://example.com/a", "第一篇"],
  ["https://example.com/b", "第二篇"],
  ["https://example.com/c", "第三篇"],
];

/**
 * What the rows say in the listing images.
 *
 * The panel, its layout and its states are all real — the sample text is not.
 * The deterministic double answers every URL with one title and one length, so
 * three rows would otherwise carry three copies of the same placeholder, which
 * reads as a broken screenshot rather than a product. Real pages were tried and
 * are the wrong answer twice over: they refuse datacenter traffic, and putting
 * another site's article titles in 立言阁's promotional material implies a
 * relationship with it.
 */
const SAMPLES = [
  ["清代书院的讲学制度与士人交往", "1 篇 · 8,412 字", "8,412 字"],
  ["从科举到学堂：教育转型中的地方财政", "5,207 字", "5,207 字"],
  ["晚清报刊中的“公论”一词", "3,164 字", "3,164 字"],
];
mkdirSync(OUT, { recursive: true });

/**
 * The page behind the popup, and the frame around it.
 *
 * Injected at screenshot time and committed nowhere: it exists to present the
 * panel, and putting it in the extension's source would be shipping a listing
 * asset inside the product.
 */
const STAGE = `
  html, body { width: 1280px !important; height: 800px !important; overflow: hidden !important; }
  body { position: relative; background: var(--canvas); }
  #stage-page {
    position: absolute; inset: 0; padding: 92px 520px 60px 120px;
    display: flex; flex-direction: column; gap: 20px;
  }
  #stage-page .t { height: 34px; width: 74%; border-radius: 6px; background: var(--ink); opacity: 0.13; }
  #stage-page .l { height: 12px; border-radius: 4px; background: var(--ink); opacity: 0.07; }
  #stage-page .l:nth-child(3n) { width: 88%; }
  #stage-page .l:nth-child(4n) { width: 95%; }
  #stage-page .l.short { width: 52%; }
  #stage-page .gap { height: 14px; }
  #root {
    position: absolute; top: 84px; right: 108px; width: 360px; z-index: 2;
    border-radius: 12px; overflow: hidden; background: var(--surface);
    box-shadow: 0 24px 70px -12px rgba(0,0,0,0.32), 0 0 0 1px var(--rule);
  }
  #stage-arrow {
    position: absolute; top: 34px; right: 250px; width: 34px; height: 34px;
    border-radius: 8px; background: var(--surface); box-shadow: 0 0 0 1px var(--rule);
    display: flex; align-items: center; justify-content: center;
  }
  #stage-arrow img { width: 20px; height: 20px; }
`;

async function stage(page) {
  await page.evaluate((css) => {
    if (document.getElementById("stage-style")) return;
    const style = document.createElement("style");
    style.id = "stage-style";
    style.textContent = css;
    document.head.append(style);

    const behind = document.createElement("div");
    behind.id = "stage-page";
    behind.innerHTML =
      '<div class="t"></div>' +
      Array.from({ length: 5 }, () => '<div class="l"></div>').join("") +
      '<div class="l short"></div><div class="gap"></div>' +
      Array.from({ length: 7 }, () => '<div class="l"></div>').join("") +
      '<div class="l short"></div><div class="gap"></div>' +
      Array.from({ length: 6 }, () => '<div class="l"></div>').join("");
    document.body.prepend(behind);

    // The toolbar icon the popup hangs from, so the shot reads as a popup.
    const button = document.createElement("div");
    button.id = "stage-arrow";
    button.innerHTML = '<img src="/icons/icon-128.png" alt="">';
    document.body.append(button);

  }, STAGE);
  await page.waitForTimeout(400);
}

/**
 * Click a button by its label, tolerating the panel re-rendering underneath.
 *
 * The panel settles in stages — it reads the account, then the basket, then the
 * current tab — so a button located the instant it appears is often detached
 * before the click lands.
 */
async function clickText(page, text) {
  const button = page.locator("button", { hasText: text }).first();
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      await button.waitFor({ state: "visible", timeout: 15000 });
      await page.waitForTimeout(600);
      await button.click({ timeout: 5000 });
      return;
    } catch (error) {
      if (attempt === 7) throw error;
    }
  }
}

/** Put the sample text on whatever rows the basket is showing. */
async function sample(page) {
  await page.evaluate((samples) => {
    document.querySelectorAll(".basket__item").forEach((item, index) => {
      const [title, , length] = samples[index] ?? [];
      if (!title) return;
      const heading = item.querySelector(".basket__title");
      if (heading) {
        heading.textContent = title;
        heading.classList.remove("basket__title--pending");
      }
      const pill = item.querySelector(".basket__pill");
      if (pill) pill.textContent = length;
      const host = item.querySelector(".basket__host");
      if (host) host.textContent = ["shuyuan.example.org", "difang-caizheng.example.org", "baokan.example.org"][index] ?? "";
    });
    // 已创建 names the task, and the server names it after the first 来源 — so
    // it carries the double's placeholder unless it is sampled too.
    const task = document.querySelector(".panel__task-name");
    if (task && samples[0]) task.textContent = samples[0][0];
  }, samples());
  await page.waitForTimeout(150);
}

function samples() {
  return SAMPLES;
}

async function shot(page, name) {
  await sample(page);
  await stage(page);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log("wrote", name);
}

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();

// 1. 未登录 — the first screen after installing.
await page.goto(`${HARNESS}?signedout=1`);
await page.getByRole("textbox", { name: "邮箱" }).waitFor();
await shot(page, "1-sign-in");

// 2. 主屏 — signed in, nothing collected yet.
await page.goto(`${HARNESS}?url=${encodeURIComponent(PAGES[0][0])}&title=${encodeURIComponent(PAGES[0][1])}`);
await page.getByRole("button", { name: "新建任务" }).waitFor();
await shot(page, "2-home");

// 3. 空篮子 — the basket open, 添加当前页面 live.
await clickText(page, "新建任务");
await page.getByText(/还没有来源/).waitFor();
await shot(page, "3-empty-basket");

// 4. 装满了 — three 来源 and the 主题 field.
//
// The first 来源 goes in without reloading. An empty basket found in storage is
// treated as collected and the panel returns to 主屏 — correct behaviour, and it
// means a reload before the first 来源 exists throws the basket away.
await clickText(page, "添加当前页面");
await page.waitForTimeout(3500);
for (const [url, title] of PAGES.slice(1)) {
  await page.goto(`${HARNESS}?url=${encodeURIComponent(url)}&title=${encodeURIComponent(title)}`);
  await page.waitForTimeout(1500);
  await clickText(page, "添加当前页面");
  await page.waitForTimeout(3500);
}
await page.locator(".basket__item").nth(2).waitFor();
await shot(page, "4-three-sources");

// 5. 已创建 — the task exists and 知言 has started.
await clickText(page, "确认创建任务");
await page.getByText(/任务已创建/).waitFor({ timeout: 60000 });
await shot(page, "5-created");

await browser.close();
console.log("done ->", OUT);
