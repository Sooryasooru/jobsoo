// Hand-rolled typed client. The backend CORS default allows this dev origin.

import type {
  ApplicationEventRow,
  ApplicationRow,
  ApplicationStatus,
  ApplicationsBoard,
  AvailabilityInfo,
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body && !(init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

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
