import { supabase, supabaseEnabled } from "../lib/supabase";

const BASE = "/api/v1";

/* ==========================================================================
   API client.

   Two identity sources during the Supabase migration. Which one is in use is
   decided by build configuration, not per-request guesswork: if the build has
   Supabase credentials, the Supabase session is authoritative; otherwise the
   legacy token in localStorage is.

   `getToken()` stays synchronous because a <video> element cannot send an
   Authorization header and needs the token inline in a URL. The Supabase token
   is therefore mirrored into a module-level cache that the auth listener keeps
   current.
   ========================================================================== */

let cachedSupabaseToken: string | null = null;

/** Called by AuthContext on every auth state change. */
export function setSupabaseToken(token: string | null): void {
  cachedSupabaseToken = token;
}

export function getToken(): string | null {
  if (supabaseEnabled) return cachedSupabaseToken;
  return localStorage.getItem("token");
}

/** Authoritative token for a request. Prefers a live Supabase session over
 *  the cache, so a token refreshed mid-flight is picked up immediately rather
 *  than after the next auth event. */
async function authToken(): Promise<string | null> {
  if (!supabaseEnabled) return localStorage.getItem("token");
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const live = data.session?.access_token ?? null;
    if (live) {
      cachedSupabaseToken = live;
      return live;
    }
  }
  return cachedSupabaseToken;
}

export class ApiError extends Error {
  status: number;
  /** Machine-readable code when the server sent one; the UI uses it to decide
   *  whether to offer Retry. */
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status; // 0 = network-level failure (no HTTP response)
    this.code = code;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await authToken();
  const headers: Record<string, string> = { ...(options.headers as Record<string, string>) };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }

  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, { ...options, headers });
  } catch (err) {
    throw new ApiError(err instanceof Error ? err.message : "Network error", 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    let code: string | undefined;
    try {
      const body = await res.json();
      detail = body.detail || detail;
      code = body.code;
    } catch {
      /* ignore */
    }
    throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  postForm: <T>(path: string, form: FormData) => request<T>(path, { method: "POST", body: form }),
};
