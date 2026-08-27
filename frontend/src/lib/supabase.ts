import { createClient, type SupabaseClient } from "@supabase/supabase-js";

/* ==========================================================================
   Supabase browser client.

   Only VITE_-prefixed variables exist here, and only the anon/publishable key
   is ever one of them. The service-role key bypasses RLS entirely; it lives in
   the API container and the worker container and must never be bundled — a
   grep for it in `dist/` is part of the release checks (see
   backend/tests/test_secrets_not_in_client_bundle.py).
   ========================================================================== */

const url = import.meta.env.VITE_SUPABASE_URL ?? "";
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";

/** Whether this build is configured to talk to Supabase Auth/Storage at all.
 *  When false the app runs against the local FastAPI stack, which is the
 *  default for `npm run dev` with no environment set. */
export const supabaseEnabled = Boolean(url && anonKey);

export const supabase: SupabaseClient | null = supabaseEnabled
  ? createClient(url, anonKey, {
      auth: {
        // The session lives in localStorage and is refreshed in the
        // background, so an upload that outlives the access token does not
        // fail at 59 minutes.
        persistSession: true,
        autoRefreshToken: true,
        detectSessionInUrl: true,
        storageKey: "shuttlesense.auth",
      },
      global: { headers: { "x-client-info": "shuttlesense-web" } },
    })
  : null;

export const SUPABASE_URL = url;

/** The current Supabase access token, refreshed if it is close to expiry.
 *  Used to authorize both API calls and the direct TUS upload. */
export async function currentAccessToken(): Promise<string | null> {
  if (!supabase) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
