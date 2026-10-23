/** Thrown when the API rejects our credentials — no session, or an expired one. */
export class UnauthorizedError extends Error {
  constructor(message = "Your session has expired. Sign in again to continue.") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export const isUnauthorized = (error: unknown): boolean =>
  error instanceof UnauthorizedError;

/**
 * fetch() wrapper that attaches the current Supabase access token.
 *
 * The FPL backend verifies this token against the project's public JWKS, so
 * every call to it must carry the signed-in user's session.
 *
 * A 401 throws UnauthorizedError rather than returning the response, so every
 * caller gets the same typed failure without repeating the check — retries and
 * error rendering can then branch on a session problem instead of showing a
 * raw status code with a Retry button that can never succeed.
 *
 * The Supabase client is imported lazily: pulling it in at module load would
 * instantiate it (and touch localStorage) anywhere these API modules are
 * imported, including non-browser contexts such as the test runner.
 */
export const authFetch = async (
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> => {
  const headers = new Headers(init.headers ?? {});

  if (!headers.has("Authorization")) {
    try {
      const { supabase } = await import("@/integrations/supabase/client");
      const { data } = await supabase.auth.getSession();
      const token = data.session?.access_token;
      if (token) headers.set("Authorization", `Bearer ${token}`);
    } catch {
      // No session (or no browser storage) — send unauthenticated and let the
      // API decide.
    }
  }

  const response = await fetch(input, { ...init, headers });
  if (response.status === 401) throw new UnauthorizedError();
  return response;
};
