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
 * When each 来源 in this basket was added, by its server id.
 *
 * Kept here because the server does not send it: a settled 来源 carries no
 * timestamp, and its Execution is gone by then. The panel needs it because
 * cleanup ages each unconfirmed 来源 on its own clock, so a basket filled
 * across two days can quietly become a basket of one. Knowing when a row went
 * in is the only way to warn before that happens.
 *
 * Local is the right place for it regardless: the basket itself exists only in
 * this browser, so there is no other browser this could have been useful in.
 */
const ADDED_KEY = "liyan.creation-added-at";

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

export type AddedTimes = Record<string, number>;

export async function readAddedTimes(): Promise<AddedTimes> {
  const stored = await readStored(ADDED_KEY);
  if (!stored) return {};
  try {
    const parsed: unknown = JSON.parse(stored);
    if (!parsed || typeof parsed !== "object") return {};
    // Anything that is not a number is dropped rather than trusted: this is
    // only ever used to say how old a row is, and a wrong answer there is
    // worse than no answer.
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (entry): entry is [string, number] => typeof entry[1] === "number",
      ),
    );
  } catch {
    return {};
  }
}

export async function recordAdded(sourceId: string, at = Date.now()): Promise<void> {
  const times = await readAddedTimes();
  times[sourceId] = at;
  await writeStored(ADDED_KEY, JSON.stringify(times));
}

export async function closeBasket(): Promise<void> {
  await clearStored(BASKET_KEY);
  await clearStored(CONFIRMATION_KEY);
  await clearStored(ADDED_KEY);
}
