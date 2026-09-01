import { clearStored, readStored, writeStored } from "./storage";

/**
 * The 任务创建会话 the panel is filling, if it is filling one.
 *
 * It is stored rather than held because the panel is destroyed every time the
 * user clicks back into the page, and the session id is the only way back to
 * 来源 already submitted under it. Losing it strands them on the server where
 * nothing can reach them until cleanup takes them.
 *
 * One id per basket — not per install, and not per capture. Per capture would
 * make an orphan of every 来源 not confirmed immediately; per install would let
 * a confirmation sweep up something captured a week ago, because confirmation
 * demands every unconfirmed 来源 in its session and takes no subset.
 */
const BASKET_KEY = "liyan.creation-session";

/**
 * The key confirmation is made under, stored beside the basket it belongs to.
 *
 * It is generated once per basket rather than per attempt, so that a
 * confirmation the panel never saw the answer to — the popup closed, the
 * network dropped — is repeated rather than duplicated. The server answers a
 * replay with the task it already created.
 */
const CONFIRMATION_KEY = "liyan.creation-idempotency-key";

/**
 * What the panel knows about each 来源 it added, by the server's id for it.
 *
 * Two things the server does not send back. **When** it was added: a settled
 * 来源 carries no timestamp and its Execution is gone by then, and the panel
 * needs it because cleanup ages each unconfirmed 来源 on its own clock — so a
 * basket filled across two days can quietly become a basket of one. And
 * **which page** it was: the server keeps a `provenance`, but only once the
 * fetch has succeeded. A 来源 that failed has none, and a row that cannot say
 * which page failed is useless to the person deciding what to do about it.
 *
 * Local is the right place for both regardless: the basket itself exists only
 * in this browser, so there is no other browser this could be useful in.
 */
const ADDED_KEY = "liyan.creation-added";

export function readBasketId(): Promise<string | null> {
  return readStored(BASKET_KEY);
}

/** Open a basket locally. Nothing is sent: the session begins at its first 来源. */
export async function openBasket(): Promise<string> {
  const id = crypto.randomUUID();
  await writeStored(BASKET_KEY, id);
  await writeStored(CONFIRMATION_KEY, crypto.randomUUID());
  await writeStored(ADDED_KEY, "{}");
  return id;
}

/**
 * The idempotency key for this basket's confirmation.
 *
 * A basket recovered from an older version of the panel, or written before
 * this key existed, has none — so one is made and kept on first use rather
 * than refusing to confirm.
 */
export async function readConfirmationKey(): Promise<string> {
  const stored = await readStored(CONFIRMATION_KEY);
  if (stored) return stored;
  const created = crypto.randomUUID();
  await writeStored(CONFIRMATION_KEY, created);
  return created;
}

export type AddedSource = { at: number; url: string };
export type AddedSources = Record<string, AddedSource>;

function isAddedSource(value: unknown): value is AddedSource {
  if (!value || typeof value !== "object") return false;
  const entry = value as Record<string, unknown>;
  return typeof entry.at === "number" && typeof entry.url === "string";
}

export async function readAddedSources(): Promise<AddedSources> {
  const stored = await readStored(ADDED_KEY);
  if (!stored) return {};
  try {
    const parsed: unknown = JSON.parse(stored);
    if (!parsed || typeof parsed !== "object") return {};
    // Anything not of this shape is dropped rather than trusted. Every use of
    // it is a sentence shown to a user, and a wrong sentence is worse than a
    // missing one.
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, AddedSource] => isAddedSource(entry[1]),
      ),
    );
  } catch {
    return {};
  }
}

export async function recordAdded(
  sourceId: string,
  url: string,
  at = Date.now(),
): Promise<void> {
  const added = await readAddedSources();
  added[sourceId] = { at, url };
  await writeStored(ADDED_KEY, JSON.stringify(added));
}

export async function closeBasket(): Promise<void> {
  await clearStored(BASKET_KEY);
  await clearStored(CONFIRMATION_KEY);
  await clearStored(ADDED_KEY);
}
