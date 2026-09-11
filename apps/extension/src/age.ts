/**
 * How long a 来源 has been sitting in the basket, and when to say so.
 *
 * Cleanup ages each unconfirmed 来源 on its own timestamp, so a basket filled
 * over two days loses its oldest row without announcing it. The panel cannot
 * prevent that — extending a 来源's life is the server's to decide — but it can
 * stop it being a surprise.
 */

/**
 * 工作台's translator, passed in rather than looked up.
 *
 * These are plain functions and have to stay that way — they are what the
 * tests reason about — so the language reaches them the only way it can
 * without a hook: as an argument.
 */
type Translate = (source: string) => string;

const HOUR = 60 * 60 * 1000;

/**
 * How long the server keeps an unconfirmed 来源, as far as the panel assumes.
 *
 * This mirrors the default of `LIYAN_CLEANUP_TASK_CREATION_SESSION_TTL_HOURS`
 * rather than reading it, because nothing sends it. That makes it a hint and
 * never a rule: the panel warns, and the server decides. It is deliberately
 * used only to warn *early* — an installation configured with a longer TTL
 * makes this cautious, which is the harmless direction to be wrong in.
 */
const ASSUMED_TTL_HOURS = 24;

/** Warn once a 来源 is this close to the assumed end of its life. */
const WARN_WITHIN_HOURS = 4;

/**
 * How old a 来源 is, or null while that is not worth the space it would take.
 *
 * A row shows either its address or its age, because 360px does not hold both.
 * The address is what a user recognizes, so it wins until the age is the more
 * useful of the two — which is once the basket has outlived the sitting that
 * filled it, and its rows have started counting down.
 */
export function describeAge(
  t: Translate,
  addedAt: number | undefined,
  now = Date.now(),
): string | null {
  if (addedAt === undefined) return null;
  const elapsed = now - addedAt;
  if (elapsed < HOUR) return null;
  return t("{hours} 小时前").replace("{hours}", String(Math.floor(elapsed / HOUR)));
}

/** The sentence to show when something in the basket is about to be collected. */
export function expiryWarning(
  t: Translate,
  added: Record<string, { at: number }>,
  now = Date.now(),
): string | null {
  const oldest = Math.min(...Object.values(added).map((one) => one.at));
  if (!Number.isFinite(oldest)) return null;
  const remainingHours = ASSUMED_TTL_HOURS - (now - oldest) / HOUR;
  if (remainingHours > WARN_WITHIN_HOURS) return null;
  if (remainingHours <= 0) return t("最早添加的来源可能已被清理。");
  return t("最早添加的来源将在约 {hours} 小时后被清理。").replace(
    "{hours}",
    String(Math.max(1, Math.round(remainingHours))),
  );
}
