import { createSupabaseAuthProvider } from "@workbench/auth/provider";

import { chromeSessionStorage } from "./storage";

/**
 * The panel's sign-in: the workbench's provider over the extension's storage.
 *
 * `detectSessionInUrl` is off because a panel is opened by the browser and
 * never navigated to — there is no fragment for Supabase to find, and looking
 * for one on every open is work that can only find nothing.
 */
export const extensionAuthProvider = createSupabaseAuthProvider({
  storage: chromeSessionStorage,
  detectSessionInUrl: false,
});
