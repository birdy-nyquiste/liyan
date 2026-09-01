/**
 * Where 工作台 answers, and how the panel sends a user there.
 *
 * The 插件 has no page of its own for buying 额度 or for reading a 立言任务 —
 * both belong to 工作台, and a second surface for either would be a second
 * thing to keep true. So the panel's job is to open the right address.
 */
const WEB_BASE_URL: string = import.meta.env.VITE_WEB_BASE_URL ?? "http://localhost:5173";

export function workbenchUrl(path = "/"): string {
  return new URL(path, WEB_BASE_URL).toString();
}

/**
 * Open a workbench page in a tab of its own.
 *
 * A new tab rather than the current one: the user is reading something, and
 * that page is the reason the panel is open at all. Navigating away from it to
 * buy 额度 would lose the thing they were about to collect.
 */
export async function openWorkbench(path: string): Promise<void> {
  await chrome.tabs.create({ url: workbenchUrl(path) });
}
