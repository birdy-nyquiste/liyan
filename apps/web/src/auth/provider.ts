import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export interface AuthProvider {
  getAccessToken(): Promise<string | null>;
  sendEmailOtp(email: string): Promise<void>;
  verifyEmailOtp(email: string, token: string): Promise<string>;
  signOut(): Promise<void>;
  /**
   * Watch the session for changes, and stop watching with the returned call.
   *
   * The workbench needs this for the one transition it cannot see any other
   * way: a session that can no longer be refreshed. Supabase announces that as
   * a signed-out state with no session, and without hearing it the workbench
   * would keep a signed-in shell on screen whose every request is refused.
   */
  onAuthStateChange(listener: (accessToken: string | null) => void): () => void;
}

/**
 * Where a signed-in session is kept between page loads.
 *
 * Supabase reaches for `localStorage` by default, and that is right for the
 * workbench and absent from an extension's service worker. It is a parameter
 * rather than a second copy of this file because what a second copy would also
 * duplicate is the refresh behaviour below, and that is the part that is easy
 * to get wrong.
 */
export interface SessionStorage {
  getItem(key: string): string | null | Promise<string | null>;
  setItem(key: string, value: string): void | Promise<void>;
  removeItem(key: string): void | Promise<void>;
}

export type AuthProviderOptions = {
  storage?: SessionStorage;
  /**
   * Whether a session may arrive in the page's own URL. True for the workbench,
   * which Supabase may return to with a fragment; false for a panel, which is
   * opened by the browser and never navigated to.
   */
  detectSessionInUrl?: boolean;
};

class SupabaseAuthProvider implements AuthProvider {
  private client: SupabaseClient | null = null;

  constructor(private readonly options: AuthProviderOptions = {}) {}

  private getClient(): SupabaseClient {
    if (this.client) return this.client;

    const url = import.meta.env.VITE_SUPABASE_URL;
    const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
    if (!url || !publishableKey) {
      throw new Error("Supabase Auth is not configured.");
    }
    this.client = createClient(url, publishableKey, {
      auth: {
        storage: this.options.storage,
        detectSessionInUrl: this.options.detectSessionInUrl ?? true,
      },
    });
    return this.client;
  }

  /**
   * The access token to send right now.
   *
   * `getSession` is not a cache read: it refreshes a session whose token has
   * expired, and awaits a refresh already in flight. That is the whole reason
   * every request asks again rather than reusing what sign-in returned — an
   * access token lives about an hour, and a workbench left open longer than
   * that was sending a dead one on every call.
   */
  async getAccessToken(): Promise<string | null> {
    const { data, error } = await this.getClient().auth.getSession();
    if (error) throw error;
    return data.session?.access_token ?? null;
  }

  async sendEmailOtp(email: string): Promise<void> {
    const { error } = await this.getClient().auth.signInWithOtp({ email });
    if (error) throw error;
  }

  async verifyEmailOtp(email: string, token: string): Promise<string> {
    const { data, error } = await this.getClient().auth.verifyOtp({
      email,
      token,
      type: "email",
    });
    if (error || !data.session) throw error ?? new Error("No session returned.");
    return data.session.access_token;
  }

  async signOut(): Promise<void> {
    const { error } = await this.getClient().auth.signOut();
    if (error) throw error;
  }

  onAuthStateChange(listener: (accessToken: string | null) => void): () => void {
    const { data } = this.getClient().auth.onAuthStateChange((_event, session) => {
      listener(session?.access_token ?? null);
    });
    return () => data.subscription.unsubscribe();
  }
}

/** An 立言阁 sign-in against whatever storage the client can offer. */
export function createSupabaseAuthProvider(options: AuthProviderOptions = {}): AuthProvider {
  return new SupabaseAuthProvider(options);
}

export const supabaseAuthProvider: AuthProvider = createSupabaseAuthProvider();
