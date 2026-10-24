import { useState } from "react";
import Applications from "./views/Applications";
import Matches from "./views/Matches";
import Jobs from "./views/Jobs";
import ProfileCv from "./views/ProfileCv";
import Tailored from "./views/Tailored";

type Tab = "matches" | "jobs" | "profile" | "tailored" | "applications";

const TABS: { id: Tab; label: string }[] = [
  { id: "matches", label: "Matches" },
  { id: "jobs", label: "Jobs" },
  { id: "applications", label: "Applications" },
  { id: "profile", label: "CV & Profile" },
  { id: "tailored", label: "Tailored CV" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("matches");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [sourceCvId, setSourceCvId] = useState<string | null>(null);

  return (
    <div className="mx-auto max-w-4xl px-4 py-6">
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">jobsoo</h1>
        <p className="text-sm text-slate-500">
          Job application intelligence — every job stays visible, every claim is verified
          against your original CV.
        </p>
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
        {tab === "applications" && <Applications />}
        {tab === "profile" && <ProfileCv sourceCvId={sourceCvId} onSelectCv={setSourceCvId} />}
        {tab === "tailored" && <Tailored sourceCvId={sourceCvId} />}
      </main>
    </div>
  );
}
