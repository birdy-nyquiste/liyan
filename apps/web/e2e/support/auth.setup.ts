import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

import {
  AGAINST_STAGING,
  FIXED_OTP,
  SESSION_STATE,
  bootstrapStagingSession,
  openWorkbench,
  seedLocalSession,
  signInWithOtp,
  storedSessionIsLive,
  test,
} from "./workbench";

/**
 * Sign in once, and let every spec reuse the session.
 *
 * Not an optimization. A Supabase email code is single-use and short-lived, so
 * a suite that signs in per spec can be run exactly once, by whoever is holding
 * a fresh code, and every spec after the first fails on a code already spent.
 * Signing in here and saving the storage state is what makes the Staging run
 * repeatable within the life of one session.
 *
 * It also means the OTP journey is proven here rather than in a spec of its
 * own: this step performs the real thing against the real Supabase project, and
 * a failure stops the whole run before a single spec is attempted.
 */
test("sign in", async ({ page }) => {
  if (AGAINST_STAGING && storedSessionIsLive()) {
    // Nothing to spend a code on: the session from an earlier run is still
    // good, and re-authenticating would invalidate a code somebody is holding.
    test.skip();
    return;
  }
  if (!AGAINST_STAGING) {
    await seedLocalSession(page);
  } else if (FIXED_OTP) {
    await signInWithOtp(page);
  } else {
    // A code somebody handed us cannot survive the form: see the comment on
    // bootstrapStagingSession. Set LIYAN_E2E_FIXED_OTP=1 once Supabase has a
    // test address, and the form itself is covered again.
    await bootstrapStagingSession(page);
    await openWorkbench(page);
  }

  mkdirSync(dirname(SESSION_STATE), { recursive: true });
  await page.context().storageState({ path: SESSION_STATE });
});
