// Hand-rolled typed client. The backend CORS default allows this dev origin.

import type {
  ApplicationEventRow,
  ApplicationRow,
  ApplicationStatus,
  ApplicationsBoard,
  AvailabilityInfo,
  AuthUser,
} from "./types";

export const API_BASE: string =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Bearer session token lifecycle (see docs/security.md):
// - Kept in localStorage for a local, single-user-per-browser dev app. Cookie
//   sessions would need CORS credentials + CSRF handling for no extra safety
//   here; this is the documented trade-off.
// - Cleared as soon as the backend replies 401 (expired/revoked token).
const TOKEN_KEY = "jobsoo_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null; // jsdom/private mode
  }
}

export function setToken(token: string | null): void {
  try {
    if (token === null) {
      localStorage.removeItem(TOKEN_KEY);
    } else {
      localStorage.setItem(TOKEN_KEY, token);
    }
  } catch {
    // storage unavailable: session ends when the tab closes
  }
}

export const SESSION_EXPIRED_EVENT = "jobsoo:session-expired";

// FastAPI/Pydantic `detail` is a plain string for hand-raised errors but an
// array of {loc, msg} objects for 422 validation errors. Flatten both into
// one readable, user-safe line (no stack traces, no internals).
function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((issue) => {
        if (!issue || typeof issue !== "object") return null;
        const { loc, msg } = issue as { loc?: unknown; msg?: unknown };
        const field = Array.isArray(loc)
          ? loc.filter((p) => typeof p === "string").slice(1).join(" ")
          : "";
        const message = typeof msg === "string" ? msg : null;
        if (!message) return null;
        return field ? `${field}: ${message}` : message;
      })
      .filter((p): p is string => p !== null);
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  // A rejection here means fetch() itself failed - backend unreachable, DNS,
  // or a CORS-blocked origin. It propagates unchanged so callers can show a
  // genuine connectivity error distinct from HTTP-level API errors.
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && path !== "/auth/register") {
      // Expired or revoked session: drop the stale token and notify listeners.
      setToken(null);
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }
    let detail = response.statusText || `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = formatDetail(body.detail) ?? detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  // Success: tolerate 204/empty bodies (logout) and non-JSON payloads, which
  // must surface as a server-response error, never as a fake "network error".
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError(502, "the server returned an unexpected response");
  }
}

interface TokenPayload {
  token: string;
  user: AuthUser;
}

export const authApi = {
  register: (email: string, password: string, displayName = "") =>
    request<TokenPayload>("/auth/register", {
      method: "POST",
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),
  login: (email: string, password: string) =>
    request<TokenPayload>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<AuthUser>("/auth/me"),
};

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  uploadCv: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ id: string; original_filename: string; parse_notes: string[] }>("/cvs", {
      method: "POST",
      body: form,
    });
  },
};

export const applicationsApi = {
  board: () => api.get<ApplicationsBoard>("/applications"),
  get: (id: string) => api.get<ApplicationRow>(`/applications/${id}`),
  create: (jobId: string, tailoredResumeId?: string) =>
    api.post<ApplicationRow>("/applications", {
      job_id: jobId,
      ...(tailoredResumeId ? { tailored_resume_id: tailoredResumeId } : {}),
    }),
  events: (id: string) =>
    api.get<ApplicationEventRow[]>(`/applications/${id}/events`),
  setStatus: (id: string, status: ApplicationStatus, notes?: string) =>
    api.post<ApplicationRow>(`/applications/${id}/status`, { status, notes: notes ?? null }),
  confirmSubmit: (id: string, externalRef?: string) =>
    api.post<ApplicationRow>(`/applications/${id}/confirm-submit`, {
      external_ref: externalRef ?? null,
    }),
  availability: (id: string) =>
    api.get<AvailabilityInfo>(`/applications/${id}/availability`),
};
