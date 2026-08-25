/**
 * How often the workbench asks the server what changed.
 *
 * There is no push channel, so every one of these is load: one open 任务详情
 * with three 来源 is one request per interval for as long as the work runs, and
 * every writer signed in adds their own. That is why the numbers live together
 * rather than beside the components that use them — the total is the thing
 * worth seeing, and it is invisible when each is a literal in its own file.
 *
 * The two speeds are a deliberate split. Intake polls fast because a user is
 * watching a 来源 they just submitted and the wait is seconds; everything else
 * polls slowly because 知言, 立言, and a Blog submission take as long as a
 * provider takes, and asking four times as often does not make any of them
 * arrive sooner.
 *
 * `docs/operations/limits.md` holds the rest of the launch limits, including
 * the ceiling on how much work one user may have running at all.
 */

/** A 来源 being fetched or parsed, with the user watching it. Seconds, not minutes. */
export const SOURCE_PREPARATION_POLL_MS = 750;

/** 知言 runs, 立言 generation, and Blog submission: provider-paced work. */
export const EXECUTION_POLL_MS = 2000;
