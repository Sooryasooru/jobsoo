import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Card, Chip, ScoreBadge, SectionTitle, Spinner, TierBadge } from "../components/ui";
import type { IngestResult, IngestStats, MatchPayload } from "../types";

export default function Matches({ onOpenJob }: { onOpenJob: (jobId: string) => void }) {
  const [matches, setMatches] = useState<MatchPayload[] | null>(null);
  const [stats, setStats] = useState<IngestStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ingestNote, setIngestNote] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [m, s] = await Promise.all([
        api.get<MatchPayload[]>("/jobs/matches/all"),
        api.get<IngestStats>("/jobs/stats"),
      ]);
      setMatches(m);
      setStats(s);
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to load matches");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const recompute = async (jobId: string) => {
    setBusy(true);
    setError(null);
    try {
      await api.post<MatchPayload>(`/jobs/${jobId}/match`);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to recompute");
    } finally {
      setBusy(false);
    }
  };

  const ingest = async () => {
    setBusy(true);
    setIngestNote(null);
    try {
      const result = await api.post<IngestResult>("/jobs/ingest");
      setIngestNote(
        `Ingested ${result.total_seen} postings: ${result.inserted} new, ${result.updated} reconciled.`,
      );
      await load();
    } catch (exc) {
      setIngestNote(
        exc instanceof ApiError ? `Ingest failed: ${exc.message}` : "Ingest failed.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (error && matches === null) return <p className="text-rose-700">{error}</p>;
  if (matches === null) return <Spinner />;

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <SectionTitle>
            {stats ? `${stats.total} jobs stored (${stats.active} active, ${stats.expired} expired)` : "Job stats"}
          </SectionTitle>
          <div className="flex gap-2">
            <button
              className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              onClick={ingest}
              disabled={busy}
            >
              Ingest from Adzuna
            </button>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
              onClick={() => void load()}
              disabled={busy}
            >
              Refresh
            </button>
          </div>
        </div>
        {ingestNote && <p className="mt-2 text-sm text-slate-600">{ingestNote}</p>}
        {error && <p className="mt-2 text-sm text-rose-700">{error}</p>}
      </Card>

      {matches.length === 0 ? (
        <Card>
          <p className="text-sm text-slate-600">
            No matches computed yet. Open the <b>Jobs</b> tab, extract requirements for a job,
            then compute its match.
          </p>
        </Card>
      ) : (
        matches.map((m) => (
          <Card key={m.job_id}>
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <div className="flex items-center gap-2">
                  <ScoreBadge score={m.score} />
                  <TierBadge tier={m.tier} />
                  <span className="text-xs text-slate-500">{m.recommendation}</span>
                </div>
                <button
                  className="mt-1 text-left font-semibold text-slate-900 underline-offset-2 hover:underline"
                  onClick={() => onOpenJob(m.job_id)}
                >
                  {m.job_title ?? m.job_id}
                </button>
                <p className="text-sm text-slate-600">
                  {[m.job_company, m.job_location].filter(Boolean).join(" · ") || "—"}
                </p>
              </div>
              <button
                className="rounded border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-50 disabled:opacity-50"
                onClick={() => void recompute(m.job_id)}
                disabled={busy}
              >
                Recompute
              </button>
            </div>
            <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
              <div>
                <SectionTitle>Matched skills</SectionTitle>
                <div className="flex flex-wrap gap-1">
                  {m.matched_skills.length ? (
                    m.matched_skills.map((s) => <Chip key={s}>{s}</Chip>)
                  ) : (
                    <span className="text-slate-500">none</span>
                  )}
                </div>
                {m.missing_skills.length > 0 && (
                  <>
                    <SectionTitle>Missing skills</SectionTitle>
                    <div className="flex flex-wrap gap-1">
                      {m.missing_skills.map((s) => (
                        <Chip key={s} tone="amber">
                          {s}
                        </Chip>
                      ))}
                    </div>
                  </>
                )}
                {m.unknown_skills.length > 0 && (
                  <>
                    <SectionTitle>Unknown (unverified)</SectionTitle>
                    <div className="flex flex-wrap gap-1">
                      {m.unknown_skills.map((s) => <Chip key={s}>{s}</Chip>)}
                    </div>
                  </>
                )}
              </div>
              <div>
                {m.experience_gap_years !== null && (
                  <p className="text-slate-700">
                    Experience gap: <b>{m.experience_gap_years} year(s)</b> — a stretch indicator,
                    not an automatic rejection.
                  </p>
                )}
                {m.hard_blocker_warnings.length > 0 && (
                  <div className="mt-2">
                    <SectionTitle>Hard-blocker warnings (review these)</SectionTitle>
                    <ul className="list-inside list-disc space-y-0.5 text-rose-700">
                      {m.hard_blocker_warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {m.unknown_requirements.length > 0 && (
                  <p className="mt-2 text-xs text-slate-500">
                    Unknown requirements: {m.unknown_requirements.join(", ")}
                  </p>
                )}
              </div>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
