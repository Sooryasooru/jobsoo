import { useState, type FormEvent } from "react";
import { ApiError, authApi, setToken } from "../api";
import type { AuthUser } from "../types";

type Mode = "login" | "register";

interface AuthProps {
  onAuthenticated: (user: AuthUser) => void;
}

export default function Auth({ onAuthenticated }: AuthProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (busy) return;
    setBusy(true);
    try {
      const payload =
        mode === "login"
          ? await authApi.login(email.trim(), password)
          : await authApi.register(email.trim(), password, displayName.trim());
      setToken(payload.token);
      onAuthenticated(payload.user);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "network error; is the backend running?");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto mt-10 max-w-sm">
      <h1 className="mb-1 text-2xl font-bold tracking-tight text-slate-900">jobsoo</h1>
      <p className="mb-6 text-sm text-slate-500">
        {mode === "login" ? "Sign in to your workspace." : "Create your workspace account."}
      </p>

      <form
        className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        onSubmit={submit}
        noValidate
      >
        <div className="mb-4 flex gap-2 text-sm">
          <button
            type="button"
            className={`flex-1 rounded-md border px-3 py-1.5 ${
              mode === "login"
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-200 text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() => setMode("login")}
          >
            Sign in
          </button>
          <button
            type="button"
            className={`flex-1 rounded-md border px-3 py-1.5 ${
              mode === "register"
                ? "border-slate-900 bg-slate-900 text-white"
                : "border-slate-200 text-slate-600 hover:bg-slate-50"
            }`}
            onClick={() => setMode("register")}
          >
            Register
          </button>
        </div>

        <label className="mb-3 block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
            placeholder="you@example.com"
            autoComplete="email"
          />
        </label>

        {mode === "register" && (
          <label className="mb-3 block text-sm">
            <span className="mb-1 block font-medium text-slate-700">Display name (optional)</span>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
              placeholder="Your name"
            />
          </label>
        )}

        <label className="mb-4 block text-sm">
          <span className="mb-1 block font-medium text-slate-700">Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
            placeholder={mode === "register" ? "at least 8 characters" : ""}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>

        {error && (
          <p role="alert" className="mb-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}

        <button
          type="submit"
          data-testid="auth-submit"
          disabled={busy}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-50"
        >
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
    </div>
  );
}
