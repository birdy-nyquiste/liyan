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

export function readBasketId(): Promise<string | null> {
  return readStored(BASKET_KEY);
}

/** Open a basket locally. Nothing is sent: the session begins at its first 来源. */
export async function openBasket(): Promise<string> {
  const id = crypto.randomUUID();
  await writeStored(BASKET_KEY, id);
  return id;
}

export function closeBasket(): Promise<void> {
  return clearStored(BASKET_KEY);
}
