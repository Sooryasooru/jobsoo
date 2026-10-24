import { useCallback, useEffect, useState } from "react";
import { getToken, setToken, authApi, SESSION_EXPIRED_EVENT } from "./api";
import type { AuthUser } from "./types";
import Applications from "./views/Applications";
import AssistedApply from "./views/AssistedApply";
import Auth from "./views/Auth";
import Matches from "./views/Matches";
import Jobs from "./views/Jobs";
import ProfileCv from "./views/ProfileCv";
import Tailored from "./views/Tailored";

type Tab = "matches" | "jobs" | "profile" | "tailored" | "applications" | "assisted-apply";

const TABS: { id: Tab; label: string }[] = [
  { id: "matches", label: "Matches" },
  { id: "jobs", label: "Jobs" },
  { id: "assisted-apply", label: "Assisted Apply" },
  { id: "applications", label: "Applications" },
  { id: "profile", label: "CV & Profile" },
  { id: "tailored", label: "Tailored CV" },
];

function Dashboard({
  user,
  onLogout,
}: {
  user: AuthUser;
  onLogout: () => void;
}) {
  const [tab, setTab] = useState<Tab>("matches");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [sourceCvId, setSourceCvId] = useState<string | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);

  async function logout() {
    if (loggingOut) return;
    setLoggingOut(true);
    try {
      await authApi.logout();
    } catch {
      // Token may already be dead; clearing it below is what matters.
    } finally {
      setToken(null);
      onLogout();
    }
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <header className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">jobsoo</h1>
          <p className="text-sm text-slate-500">
            Job application intelligence — every job stays visible, every claim is verified
            against your original CV.
          </p>
        </div>
        <div className="flex items-center gap-3 whitespace-nowrap text-sm">
          <span className="text-slate-500">{user.email}</span>
          <button
            type="button"
            onClick={logout}
            disabled={loggingOut}
            className="rounded-md border border-slate-300 px-3 py-1.5 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            {loggingOut ? "Signing out…" : "Sign out"}
          </button>
        </div>
      </header>
      <nav className="mb-5 flex gap-1 border-b border-slate-200">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t.id
                ? "border-b-2 border-slate-900 font-semibold text-slate-900"
                : "text-slate-500 hover:text-slate-800"
            }`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <main>
        {tab === "matches" && <Matches onOpenJob={(id) => { setSelectedJobId(id); setTab("jobs"); }} />}
        {tab === "jobs" && <Jobs selectedJobId={selectedJobId} onSelectJob={setSelectedJobId} />}
        {tab === "assisted-apply" && (
          <AssistedApply onNavigate={(target) => setTab(target as Tab)} />
        )}
        {tab === "applications" && <Applications />}
        {tab === "profile" && <ProfileCv sourceCvId={sourceCvId} onSelectCv={setSourceCvId} />}
        {tab === "tailored" && <Tailored sourceCvId={sourceCvId} />}
      </main>
    </div>
  );
}

export default function App() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [booting, setBooting] = useState<boolean>(() => getToken() !== null);

  const expireSession = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  // Validate the stored token once at startup (and after any expiry event).
  useEffect(() => {
    if (!getToken()) {
      setUser(null);
      setBooting(false);
      return;
    }
    let alive = true;
    authApi
      .me()
      .then((me) => {
        if (alive) setUser(me);
      })
      .catch(() => {
        if (alive) expireSession(); // 401 or backend down: show the sign-in screen
      })
      .finally(() => {
        if (alive) setBooting(false);
      });
    return () => {
      alive = false;
    };
  }, [expireSession]);

  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED_EVENT, expireSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, expireSession);
  }, [expireSession]);

  if (booting) {
    return (
      <div className="mx-auto max-w-4xl px-4 py-10 text-sm text-slate-500">Restoring session…</div>
    );
  }

  if (!user) return <Auth onAuthenticated={setUser} />;
  return <Dashboard user={user} onLogout={() => setUser(null)} />;
}
