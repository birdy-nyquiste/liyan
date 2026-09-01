import { clearStored, readStored, writeStored } from "./storage";

/**
 * A sign-in halfway through, kept where the panel's own death cannot reach it.
 *
 * The panel is destroyed the moment the user clicks away — and going to read
 * the code is *the* thing they must do between the two halves of signing in.
 * Held in memory, the 验证码 screen and the address typed into it were gone by
 * the time they came back with the code, and the only way forward was to spend
 * another one. Which is the same trap again, indefinitely.
 *
 * Only the address is kept. The code is Supabase's to verify and is never
 * written down; `verifyOtp` needs nothing else from the request that sent it,
 * which is what makes resuming possible at all.
 */
const PROGRESS_KEY = "liyan.sign-in";

/**
 * How long a pending sign-in is offered before the panel starts over.
 *
 * Matched to Supabase's own default code lifetime rather than guessed: past it,
 * every code the user could be holding is dead, and resuming would put them in
 * front of a field that cannot accept anything. Starting over still keeps the
 * address, so nothing is retyped.
 */
const CODE_LIFETIME_MS = 60 * 60 * 1000;

export type SignInProgress = { email: string; sentAt: number };

export async function readSignInProgress(now = Date.now()): Promise<SignInProgress | null> {
  const stored = await readStored(PROGRESS_KEY);
  if (!stored) return null;
  try {
    const parsed: unknown = JSON.parse(stored);
    if (!parsed || typeof parsed !== "object") return null;
    const { email, sentAt } = parsed as Record<string, unknown>;
    if (typeof email !== "string" || typeof sentAt !== "number") return null;
    if (now - sentAt > CODE_LIFETIME_MS) return { email, sentAt: 0 };
    return { email, sentAt };
  } catch {
    return null;
  }
}

export async function rememberSignInProgress(email: string, at = Date.now()): Promise<void> {
  await writeStored(PROGRESS_KEY, JSON.stringify({ email, sentAt: at }));
}

export function forgetSignInProgress(): Promise<void> {
  return clearStored(PROGRESS_KEY);
}
