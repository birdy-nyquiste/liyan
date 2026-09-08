/**
 * The 440x280 small promotional tile the Web Store listing requires.
 *
 * Without one, the Store sorts the item below every item that has one. The
 * brief from Google is "avoid text" and "make sure it works at half size", so
 * this is the brand lockup and one figure — three 来源 becoming one 立言任务 —
 * and no marketing copy, which belongs to the author rather than to a script.
 *
 * Palette taken from apps/web/src/styles.css rather than eyeballed.
 */
import { chromium } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";

const OUT = process.argv[2] ?? ".";
mkdirSync(OUT, { recursive: true });

const mark = readFileSync(
  new URL("../apps/web/public/liyan-mark.svg", import.meta.url),
  "utf8",
);
const markUrl = `data:image/svg+xml;base64,${Buffer.from(mark).toString("base64")}`;

const html = `<!doctype html><meta charset="utf-8"><style>
  :root {
    --ink: #29261f; --ink-muted: #6e685b; --accent: #856b37;
    --accent-soft: #efe7d4; --surface: #fffdf8; --canvas: #f3efe6;
    --rule: rgb(66 57 39 / 14%);
  }
  * { margin: 0; box-sizing: border-box; }
  body {
    width: 440px; height: 280px; overflow: hidden;
    background:
      radial-gradient(120% 100% at 78% 8%, rgb(255 255 255 / 78%), transparent 62%),
      var(--canvas);
    display: flex; flex-direction: column; justify-content: space-between;
    padding: 34px 38px;
    font-family: "PingFang SC", "Noto Sans SC", system-ui, sans-serif;
    color: var(--ink);
  }
  .brand { display: flex; align-items: center; gap: 12px; }
  .brand img { width: 44px; height: 44px; }
  .brand span {
    font-family: "Songti SC", "Noto Serif SC", serif;
    font-size: 40px; font-weight: 600; letter-spacing: 0.06em;
  }
  /* Three sources gathered into one article: the extension's whole job, drawn
     rather than described, so it survives being shrunk to half size. */
  .figure { display: flex; align-items: center; gap: 20px; }
  .sources { display: flex; flex-direction: column; gap: 9px; }
  .card {
    width: 116px; height: 30px; border-radius: 7px; background: var(--surface);
    box-shadow: 0 1px 0 rgb(41 38 31 / 6%), 0 0 0 1px var(--rule);
    display: flex; align-items: center; gap: 8px; padding: 0 10px;
  }
  .card i { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); opacity: .55; }
  .card u { flex: 1; height: 5px; border-radius: 3px; background: var(--ink); opacity: .13; }
  .arrow { width: 46px; height: 2px; background: var(--accent); opacity: .5; position: relative; }
  .arrow::after {
    content: ""; position: absolute; right: -1px; top: -4px;
    border: 5px solid transparent; border-left-color: var(--accent); opacity: .85;
  }
  .doc {
    width: 104px; height: 122px; border-radius: 9px; background: var(--surface);
    box-shadow: 0 6px 22px -8px rgb(41 38 31 / 28%), 0 0 0 1px var(--rule);
    padding: 15px 14px; display: flex; flex-direction: column; gap: 8px;
  }
  .doc b { display: block; height: 8px; width: 66%; border-radius: 3px; background: var(--accent); opacity: .6; }
  .doc u { display: block; height: 5px; border-radius: 3px; background: var(--ink); opacity: .14; }
  .doc u:nth-of-type(4) { width: 72%; }
</style>
<div class="brand"><img src="${markUrl}" alt=""><span>立言阁</span></div>
<div class="figure">
  <div class="sources">
    <div class="card"><i></i><u></u></div>
    <div class="card"><i></i><u></u></div>
    <div class="card"><i></i><u></u></div>
  </div>
  <div class="arrow"></div>
  <div class="doc"><b></b><u></u><u></u><u></u><u></u><u></u><u></u></div>
</div>`;

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 440, height: 280 },
  deviceScaleFactor: 1,
});
await page.setContent(html);
await page.waitForTimeout(500);
await page.screenshot({ path: `${OUT}/promo-tile-440x280.png` });
await browser.close();
console.log("wrote promo-tile-440x280.png");
