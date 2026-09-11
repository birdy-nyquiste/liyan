import type { InterfaceLocale } from "@workbench/interfaceLocale";

/**
 * Which language the panel draws itself in, decided by the browser.
 *
 * 工作台 lets a signed-in user pick, and remembers the choice in
 * `localStorage`. The panel does neither, and both halves of that are
 * deliberate: a popup that lives for seconds at a time is the wrong place to
 * put a setting, and it could not read 工作台's choice anyway — an extension
 * has its own origin, so the two do not share storage.
 *
 * So it follows Chrome instead. A browser set to Chinese is a reader of
 * 立言阁's own language; everything else gets the English the Web Store listing
 * is written in.
 */
export function preferredLocale(): InterfaceLocale {
  return isChinese(browserLanguage()) ? "zh" : "en";
}

/**
 * Chrome's UI language, or the page's if there is no Chrome to ask.
 *
 * `chrome.i18n.getUILanguage` is the browser's own setting rather than the
 * list of languages a site is offered, which is what "follows the browser"
 * should mean. `navigator.language` is what the harness has — and what a
 * `chrome.i18n` that a future manifest change removes would leave behind.
 */
function browserLanguage(): string {
  const i18n = (globalThis as { chrome?: { i18n?: { getUILanguage?(): string } } }).chrome?.i18n;
  return i18n?.getUILanguage?.() ?? globalThis.navigator?.language ?? "en";
}

/**
 * Whether a language tag names Chinese, in any of the ways Chrome writes it.
 *
 * `zh`, `zh-CN`, `zh-Hant-TW` all begin the same way; `zho` and `zhuang` do
 * not, and matching a bare prefix would claim both. The separator is what
 * tells them apart.
 */
function isChinese(tag: string): boolean {
  const lower = tag.toLowerCase();
  return lower === "zh" || lower.startsWith("zh-") || lower.startsWith("zh_");
}
