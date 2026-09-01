import { beforeEach, describe, expect, it, vi } from "vitest";

import { chromeSessionStorage, clearStored, readStored, writeStored } from "./storage";

/** `chrome.storage.local`, enough of it to hold values between calls. */
function fakeChromeStorage() {
  const kept = new Map<string, unknown>();
  return {
    kept,
    local: {
      get: vi.fn(async (key: string) =>
        kept.has(key) ? { [key]: kept.get(key) } : ({} as Record<string, unknown>),
      ),
      set: vi.fn(async (entries: Record<string, unknown>) => {
        for (const [key, value] of Object.entries(entries)) kept.set(key, value);
      }),
      remove: vi.fn(async (key: string) => {
        kept.delete(key);
      }),
    },
  };
}

let storage: ReturnType<typeof fakeChromeStorage>;

beforeEach(() => {
  storage = fakeChromeStorage();
  vi.stubGlobal("chrome", { storage: { local: storage.local } });
});

describe("the session storage the panel hands Supabase", () => {
  it("round-trips a value", async () => {
    await chromeSessionStorage.setItem("session", "a-token");
    await expect(chromeSessionStorage.getItem("session")).resolves.toBe("a-token");
  });

  it("answers null for a key it has never held", async () => {
    await expect(chromeSessionStorage.getItem("session")).resolves.toBeNull();
  });

  /**
   * `chrome.storage` will return whatever was written to it, and something else
   * may have written to the same key. Supabase would try to parse a non-string
   * as its session and fail somewhere further away than here.
   */
  it("answers null when the stored value is not a string", async () => {
    storage.kept.set("session", { token: "a-token" });
    await expect(chromeSessionStorage.getItem("session")).resolves.toBeNull();
  });

  it("forgets a removed value", async () => {
    await chromeSessionStorage.setItem("session", "a-token");
    await chromeSessionStorage.removeItem("session");
    await expect(chromeSessionStorage.getItem("session")).resolves.toBeNull();
  });
});

describe("the panel's own stored values", () => {
  it("round-trip and clear", async () => {
    await writeStored("creation-session", "an-id");
    await expect(readStored("creation-session")).resolves.toBe("an-id");
    await clearStored("creation-session");
    await expect(readStored("creation-session")).resolves.toBeNull();
  });
});
