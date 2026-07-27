"use client";

const CSRF_KEY = "imperial_csrf";

export function rememberCsrf(token: string): void {
  window.sessionStorage.setItem(CSRF_KEY, token);
}

export function clearBrowserSession(): void {
  window.sessionStorage.removeItem(CSRF_KEY);
}

export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    let csrf = window.sessionStorage.getItem(CSRF_KEY);
    if (!csrf) {
      const response = await fetch("/api/auth/csrf", {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (response.ok) {
        const payload = await response.json() as { csrfToken: string };
        csrf = payload.csrfToken;
        rememberCsrf(csrf);
      }
    }
    if (csrf) headers.set("x-csrf-token", csrf);
  }
  const response = await fetch(input, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401 && !String(input).startsWith("/api/auth/")) {
    window.location.assign(`/login?returnTo=${encodeURIComponent(window.location.pathname)}`);
  }
  return response;
}
