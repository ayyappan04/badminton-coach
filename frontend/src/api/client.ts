import { supabase, supabaseEnabled } from "../lib/supabase";

/* --- where the API lives ---------------------------------------------------
   The API is a separate container service, not a Vercel function, so the
   frontend has to be told where it is.

   VITE_API_BASE_URL set   -> absolute cross-origin calls (production).
                              The API's CORS_ORIGINS must list this site.
   VITE_API_BASE_URL unset -> same-origin /api/v1, which is what the Vite dev
                              proxy serves and what a Vercel rewrite would
                              serve if you prefer to proxy instead.
   -------------------------------------------------------------------------- */
const API_ROOT = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/+$/, "");
const BASE = `${API_ROOT}/api/v1`;

/** Absolute URL for an API path. Exported because <video> and <img> need a
 *  URL string rather than a fetch. */
export function apiUrl(path: string): string {
  return `${BASE}${path.startsWith("/") ? path : `/${path}`}`;
}

/** Resolve a URL the API handed back. Signed storage URLs are already
 *  absolute; local-dev object routes are relative and need the API origin. */
export function resolveApiUrl(url: string): string {
  if (/^https?:\/\//i.test(url)) return url;
  return `${API_ROOT}${url.startsWith("/") ? url : `/${url}`}`;
}

/** True when the API host is unreachable rather than merely refusing us. */
export function isNetworkError(err: unknown): boolean {
  return err instanceof ApiError && err.status === 0;
}

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

  // A 200 that is not JSON means something answered that is not our API --
  // a proxy, a captive portal, or an SPA catch-all rewrite serving index.html.
  // Surfacing it as an ApiError beats letting a raw SyntaxError escape from
  // somewhere that looks like a successful request.
  try {
    return await res.json();
  } catch {
    throw new ApiError(
      "The server returned an unexpected response. The API may be misconfigured.",
      res.status,
      "non_json_response",
    );
  }
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
