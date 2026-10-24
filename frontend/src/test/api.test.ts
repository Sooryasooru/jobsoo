// Regression tests for the real fetch layer (`request()` in ../api).
// The mocked-`authApi` tests in Auth.test.tsx cover the screens; these cover
// the HTTP plumbing those mocks bypass: response parsing, error flattening,
// 204 handling, and genuine connection failures.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  authApi,
  api,
  getToken,
  setToken,
  SESSION_EXPIRED_EVENT,
} from "../api";

interface FakeResponseInit {
  ok?: boolean;
  status?: number;
  statusText?: string;
  jsonBody?: unknown;
  textBody?: string;
}

function fakeResponse({
  ok = true,
  status = 200,
  statusText = "",
  jsonBody,
  textBody,
}: FakeResponseInit): Response {
  const body =
    textBody !== undefined ? textBody : jsonBody !== undefined ? JSON.stringify(jsonBody) : "";
  return {
    ok,
    status,
    statusText,
    json: async () => JSON.parse(body) as unknown,
    text: async () => body,
  } as unknown as Response;
}

const fetchMock = vi.fn<typeof fetch>();

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request(): success paths", () => {
  it("parses a 201 registration payload (token + user)", async () => {
    const payload = { token: "tok-abc", user: { id: "u1", email: "a@b.c", display_name: "A" } };
    fetchMock.mockResolvedValue(fakeResponse({ status: 201, jsonBody: payload }));

    const result = await authApi.register("a@b.c", "password-1");
    expect(result).toEqual(payload);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/auth/register");
  });

  it("tolerates a 204 empty body (logout) instead of throwing a parse error", async () => {
    fetchMock.mockResolvedValue(fakeResponse({ status: 204, textBody: "" }));
    await expect(authApi.logout()).resolves.toBeUndefined();
  });
});

describe("request(): HTTP error paths", () => {
  it("surfaces a duplicate-email 409 detail string verbatim", async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({
        ok: false,
        status: 409,
        statusText: "Conflict",
        jsonBody: { detail: "an account with this email already exists" },
      }),
    );
    await expect(authApi.register("dup@b.c", "password-1")).rejects.toMatchObject({
      status: 409,
      message: "an account with this email already exists",
    });
  });

  it("flattens a 422 Pydantic detail array into one readable line", async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({
        ok: false,
        status: 422,
        statusText: "Unprocessable Entity",
        jsonBody: {
          detail: [
            { loc: ["body", "email"], msg: "value is not a valid email address", type: "email" },
            { loc: ["body", "password"], msg: "String should have at least 8 characters" },
          ],
        },
      }),
    );
    const caught = await authApi.register("bad", "x").catch((e: unknown) => e);
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
    expect((caught as ApiError).message).toBe(
      "email: value is not a valid email address; " +
        "password: String should have at least 8 characters",
    );
  });

  it("keeps statusText when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ ok: false, status: 500, statusText: "Internal Server Error", textBody: "<html>" }),
    );
    await expect(api.get("/jobs")).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });

  it("reports a non-JSON *success* body as a server-response error, not a network error", async () => {
    fetchMock.mockResolvedValue(
      fakeResponse({ status: 201, textBody: "<!doctype html>oops" }),
    );
    const caught = await authApi.register("a@b.c", "password-1").catch((e: unknown) => e);
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(502);
    expect((caught as ApiError).message).toBe("the server returned an unexpected response");
  });
});

describe("request(): connection failures", () => {
  it("lets a genuine fetch failure propagate unchanged (backend down / CORS blocked)", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const caught = await authApi.login("a@b.c", "password-1").catch((e: unknown) => e);
    expect(caught).toBeInstanceOf(TypeError);
    expect(caught).not.toBeInstanceOf(ApiError); // so the UI shows the connectivity message
  });
});

describe("request(): 401 session handling", () => {
  it("clears the token and broadcasts expiry on a 401 from a protected route", async () => {
    setToken("tok-stale");
    const expired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    fetchMock.mockResolvedValue(
      fakeResponse({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
        jsonBody: { detail: "authentication required" },
      }),
    );

    await expect(api.get("/applications")).rejects.toBeInstanceOf(ApiError);
    expect(getToken()).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
    window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  });

  it("does NOT broadcast session expiry for failed logins (wrong password)", async () => {
    const expired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    fetchMock.mockResolvedValue(
      fakeResponse({
        ok: false,
        status: 401,
        statusText: "Unauthorized",
        jsonBody: { detail: "invalid email or password" },
      }),
    );

    await expect(authApi.login("a@b.c", "wrong")).rejects.toMatchObject({
      status: 401,
      message: "invalid email or password",
    });
    expect(expired).not.toHaveBeenCalled();
    window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  });
});
