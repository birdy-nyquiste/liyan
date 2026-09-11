import { afterEach, describe, expect, it, vi } from "vitest";

import { preferredLocale } from "./locale";

/**
 * Which language a user gets, decided once and never asked about again.
 *
 * The panel has no language setting and cannot read 工作台's, so this function
 * is the whole of the decision — and getting it wrong is not a cosmetic
 * failure. A Chinese reader who is handed English has no way to change it back.
 */

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

/** Chrome, present only for `i18n`, as it is in a real popup. */
function chromeLanguage(tag: string) {
  vi.stubGlobal("chrome", { i18n: { getUILanguage: () => tag } });
}

function navigatorLanguage(tag: string) {
  vi.spyOn(navigator, "language", "get").mockReturnValue(tag);
}

describe("preferredLocale", () => {
  it.each(["zh", "zh-CN", "zh-TW", "zh-Hant-TW", "ZH-cn"])("is Chinese for %s", (tag) => {
    chromeLanguage(tag);
    expect(preferredLocale()).toBe("zh");
  });

  it.each(["en", "en-GB", "ja", "de-DE", "zho", "zhuang"])("is English for %s", (tag) => {
    // `zho` and `zhuang` are the reason the separator is checked rather than
    // the first two letters: neither of them is Chinese.
    chromeLanguage(tag);
    expect(preferredLocale()).toBe("en");
  });

  it("prefers Chrome's own setting to the page's", () => {
    chromeLanguage("zh-CN");
    navigatorLanguage("en-US");
    // Following the browser means the browser's language, not the list of
    // languages a page is offered — the popup is Chrome's own surface.
    expect(preferredLocale()).toBe("zh");
  });

  it("falls back to the page when there is no Chrome to ask", () => {
    // The harness has no `chrome.i18n`, and neither would a popup built by a
    // manifest that stopped declaring it.
    navigatorLanguage("zh-CN");
    expect(preferredLocale()).toBe("zh");
  });
});
