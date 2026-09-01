import type { SessionStorage } from "@workbench/auth/provider";

/**
 * `chrome.storage.local` in the shape Supabase expects of `localStorage`.
 *
 * The panel is destroyed every time the user clicks back into the page, so
 * nothing may be held in memory that the next opening needs. `chrome.storage`
 * is the only store that survives that and is reachable from a service worker,
 * where `localStorage` does not exist at all.
 *
 * Every call is asynchronous, which `localStorage` is not — Supabase accepts a
 * storage whose reads return promises, and that is the whole reason this can be
 * a parameter rather than a shim that pretends to be synchronous.
 */
export const chromeSessionStorage: SessionStorage = {
  async getItem(key) {
    const stored = await chrome.storage.local.get(key);
    const value = stored[key];
    return typeof value === "string" ? value : null;
  },
  async setItem(key, value) {
    await chrome.storage.local.set({ [key]: value });
  },
  async removeItem(key) {
    await chrome.storage.local.remove(key);
  },
};

/** Read one of the panel's own stored values, or null when it has none. */
export async function readStored(key: string): Promise<string | null> {
  const stored = await chrome.storage.local.get(key);
  const value = stored[key];
  return typeof value === "string" ? value : null;
}

export async function writeStored(key: string, value: string): Promise<void> {
  await chrome.storage.local.set({ [key]: value });
}

export async function clearStored(key: string): Promise<void> {
  await chrome.storage.local.remove(key);
}
