import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { authApi, getToken, setToken, ApiError } from "../api";
import type { AuthUser } from "../types";
import App from "../App";
import Auth from "../views/Auth";

vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return { ...actual, authApi: { register: vi.fn(), login: vi.fn(), logout: vi.fn(), me: vi.fn() } };
});

const auth = vi.mocked(authApi);

function user(overrides: Partial<AuthUser> = {}): AuthUser {
  return { id: "u1", email: "test@example.com", display_name: "Test", ...overrides };
}

beforeEach(() => {
  localStorage.clear();
  auth.me.mockReset();
  auth.login.mockReset();
  auth.register.mockReset();
  auth.logout.mockReset();
  // Isolation from the real backend: dashboard views (the default Matches
  // tab) fire real api.get() calls through the actual request() client. With
  // a local backend running, those requests 401 the fake test token and
  // dispatch SESSION_EXPIRED_EVENT mid-test, racing (and preempting) the
  // sign-out flow. Stubbing fetch to reject emulates CI's unreachable
  // backend: connection-level failure only, never an HTTP 401, so no
  // session-expired event can leak in from the developer's environment.
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Auth screen", () => {
  it("submits credentials via the login API and stores the token", async () => {
    const onAuth = vi.fn();
    auth.login.mockResolvedValue({ token: "tok-1", user: user() });
    render(<Auth onAuthenticated={onAuth} />);

    await userEvent.setup().type(screen.getByLabelText("Email"), "test@example.com");
    await userEvent.setup().type(screen.getByLabelText("Password"), "valid-pass-123");
    await userEvent.setup().click(screen.getByTestId("auth-submit"));

    await waitFor(() => expect(onAuth).toHaveBeenCalledWith(user()));
    expect(auth.login).toHaveBeenCalledWith("test@example.com", "valid-pass-123");
    expect(getToken()).toBe("tok-1");
  });

  it("surfaces backend errors (e.g. wrong password)", async () => {
    auth.login.mockRejectedValue(new ApiError(401, "invalid email or password"));
    render(<Auth onAuthenticated={vi.fn()} />);

    await userEvent.setup().type(screen.getByLabelText("Email"), "test@example.com");
    await userEvent.setup().type(screen.getByLabelText("Password"), "wrong-pass");
    await userEvent.setup().click(screen.getByTestId("auth-submit"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("invalid email or password"),
    );
    expect(getToken()).toBeNull();
  });

  it("registers a new account and lands on the dashboard", async () => {
    auth.register.mockResolvedValue({ token: "tok-2", user: user() });
    render(<Auth onAuthenticated={vi.fn()} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Register" }));
    await userEvent.setup().type(screen.getByLabelText("Email"), "new@example.com");
    await userEvent.setup().type(screen.getByLabelText("Password"), "valid-pass-123");
    await userEvent.setup().click(screen.getByTestId("auth-submit"));

    await waitFor(() => expect(auth.register).toHaveBeenCalled());
    expect(auth.register).toHaveBeenCalledWith("new@example.com", "valid-pass-123", "");
  });

  it("shows the duplicate-email conflict message, not a network error", async () => {
    auth.register.mockRejectedValue(
      new ApiError(409, "an account with this email already exists"),
    );
    render(<Auth onAuthenticated={vi.fn()} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Register" }));
    await userEvent.setup().type(screen.getByLabelText("Email"), "dup@example.com");
    await userEvent.setup().type(screen.getByLabelText("Password"), "valid-pass-123");
    await userEvent.setup().click(screen.getByTestId("auth-submit"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "an account with this email already exists",
      ),
    );
    expect(screen.getByRole("alert")).not.toHaveTextContent("network error");
  });

  it("shows the connectivity message only for genuine connection failures", async () => {
    // fetch() itself rejected: backend down or CORS-blocked origin.
    auth.register.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<Auth onAuthenticated={vi.fn()} />);

    await userEvent.setup().click(screen.getByRole("button", { name: "Register" }));
    await userEvent.setup().type(screen.getByLabelText("Email"), "down@example.com");
    await userEvent.setup().type(screen.getByLabelText("Password"), "valid-pass-123");
    await userEvent.setup().click(screen.getByTestId("auth-submit"));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "network error; is the backend running?",
      ),
    );
    expect(getToken()).toBeNull();
  });
});

describe("App session handling", () => {
  it("shows the sign-in screen when no token is stored", async () => {
    render(<App />);
    await waitFor(() => expect(screen.getByText(/sign in to your workspace/i)).toBeInTheDocument());
    expect(auth.me).not.toHaveBeenCalled();
  });

  it("validates the stored token at startup and shows the dashboard", async () => {
    setToken("tok-3");
    auth.me.mockResolvedValue(user());
    render(<App />);

    await waitFor(() => expect(screen.getByText("test@example.com")).toBeInTheDocument());
    expect(auth.me).toHaveBeenCalled();
    // All the existing tabs remain reachable.
    expect(screen.getByRole("button", { name: "Assisted Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Applications" })).toBeInTheDocument();
  });

  it("falls back to sign-in when the stored token is expired", async () => {
    setToken("tok-stale");
    auth.me.mockRejectedValue(new ApiError(401, "authentication required"));
    render(<App />);

    await waitFor(() =>
      expect(screen.getByText(/sign in to your workspace/i)).toBeInTheDocument(),
    );
    expect(getToken()).toBeNull();
  });

  it("signs out via the logout API and clears the session", async () => {
    setToken("tok-4");
    auth.me.mockResolvedValue(user());
    auth.logout.mockResolvedValue(undefined);
    render(<App />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Sign out" })).toBeInTheDocument());
    await userEvent.setup().click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() =>
      expect(screen.getByText(/sign in to your workspace/i)).toBeInTheDocument(),
    );
    expect(auth.logout).toHaveBeenCalled();
    expect(getToken()).toBeNull();
  });
});
