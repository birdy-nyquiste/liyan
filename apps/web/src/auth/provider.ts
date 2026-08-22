import { createClient, type SupabaseClient } from "@supabase/supabase-js";

export interface AuthProvider {
  getAccessToken(): Promise<string | null>;
  sendEmailOtp(email: string): Promise<void>;
  verifyEmailOtp(email: string, token: string): Promise<string>;
  signOut(): Promise<void>;
}

class SupabaseAuthProvider implements AuthProvider {
  private client: SupabaseClient | null = null;

  private getClient(): SupabaseClient {
    if (this.client) return this.client;

    const url = import.meta.env.VITE_SUPABASE_URL;
    const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
    if (!url || !publishableKey) {
      throw new Error("Supabase Auth is not configured.");
    }
    this.client = createClient(url, publishableKey);
    return this.client;
  }

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
}

export const supabaseAuthProvider: AuthProvider = new SupabaseAuthProvider();
