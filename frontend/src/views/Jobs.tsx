import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Card, Chip, ScoreBadge, SectionTitle, Spinner, TierBadge } from "../components/ui";
import type { ExtractionResult, Job, JobsPage, MatchPayload, RequirementRow } from "../types";

export default function Jobs({
  selectedJobId,
  onSelectJob,
}: {
  selectedJobId: string | null;
  onSelectJob: (jobId: string | null) => void;
}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<JobsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<{
    job: Job;
    requirements: RequirementRow[] | null;
    match: MatchPayload | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);

  const loadList = useCallback(async (q: string) => {
    setError(null);
    try {
      setPage(await api.get<JobsPage>(`/jobs?q=${encodeURIComponent(q)}`));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to load jobs");
    }
  }, []);

  useEffect(() => {
    void loadList(query);
    // Initial list load only; query changes go through the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const loadDetail = useCallback(async (jobId: string) => {
    setBusy(true);
    setError(null);
    try {
      const job = await api.get<Job>(`/jobs/${jobId}`);
      let requirements: RequirementRow[] | null = null;
      let match: MatchPayload | null = null;
      try {
        requirements = await api.get<RequirementRow[]>(`/jobs/${jobId}/requirements`);
      } catch (exc) {
        if (!(exc instanceof ApiError && exc.status === 404)) throw exc;
      }
      try {
        match = await api.get<MatchPayload>(`/jobs/${jobId}/match`);
      } catch (exc) {
        if (!(exc instanceof ApiError && exc.status === 404)) throw exc;
      }
      setDetail({ job, requirements, match });
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to load job");
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (selectedJobId) void loadDetail(selectedJobId);
    else setDetail(null);
  }, [selectedJobId, loadDetail]);

  const extract = async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<ExtractionResult>(`/jobs/${detail.job.id}/requirements/extract`);
      const rows = await api.get<RequirementRow[]>(`/jobs/${detail.job.id}/requirements`);
      setDetail({ ...detail, requirements: rows });
      alert(
        `Extraction ${result.from_cache ? "(cached)" : "complete"}: ` +
          `${result.extraction.required_skills.length} required, ` +
          `${result.extraction.unknown_fields.length} unknown fields reported.`,
      );
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "extraction failed");
    } finally {
      setBusy(false);
    }
  };

  const computeMatch = async () => {
    if (!detail) return;
    setBusy(true);
    setError(null);
    try {
      const match = await api.post<MatchPayload>(`/jobs/${detail.job.id}/match`);
      setDetail({ ...detail, match });
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to compute match");
    } finally {
      setBusy(false);
    }
  };

  if (selectedJobId && detail) {
    const { job, requirements, match } = detail;
    return (
      <div className="space-y-4">
        <button
          className="text-sm text-sky-700 hover:underline"
          onClick={() => onSelectJob(null)}
        >
          ← Back to job list
        </button>
        {error && <p className="text-sm text-rose-700">{error}</p>}
        <Card>
          <h2 className="text-lg font-bold text-slate-900">{job.title}</h2>
          <p className="text-sm text-slate-600">
            {[job.company, job.location].filter(Boolean).join(" · ") || "—"} · source{" "}
            {job.source} · {job.is_remote ? "remote" : "on-site/unknown"}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              className="rounded bg-slate-800 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
              onClick={() => void extract()}
              disabled={busy}
            >
              Extract requirements (AI)
            </button>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
              onClick={() => void computeMatch()}
              disabled={busy}
            >
              Compute match score
            </button>
            <a
              className="text-sm text-sky-700 underline self-center"
              href={job.original_url}
              target="_blank"
              rel="noreferrer"
            >
              Original posting ↗
            </a>
          </div>
          {job.description && (
            <p className="mt-3 max-h-48 overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">
              {job.description}
            </p>
          )}
        </Card>

        {requirements && (
          <Card>
            <SectionTitle>Extracted requirements ({requirements.length})</SectionTitle>
            <ul className="space-y-1 text-sm">
              {requirements.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2">
                  <Chip>{r.category}</Chip>
                  <span className="text-slate-800">{r.text}</span>
                  {r.is_required && <Chip tone="amber">required</Chip>}
                  {r.is_hard_blocker && <Chip tone="rose">hard blocker</Chip>}
                  {r.min_years !== null && <Chip>{r.min_years} y</Chip>}
                </li>
              ))}
            </ul>
          </Card>
        )}

        {match && (
          <Card>
            <div className="flex items-center gap-2">
              <ScoreBadge score={match.score} />
              <TierBadge tier={match.tier} />
              <span className="text-xs text-slate-500">{match.recommendation}</span>
            </div>
            <p className="mt-2 text-xs text-slate-500">
              Rule set {match.scoring_rules_version}. Scores are explainable comparisons, not
              hiring probabilities.
            </p>
            <div className="mt-3">
              <SectionTitle>Score components</SectionTitle>
              <ul className="space-y-1 text-sm">
                {match.score_components.map((c) => (
                  <li key={c.name} className="flex flex-wrap justify-between gap-4">
                    <span className="text-slate-700">
                      {c.name}
                      {c.unknown_weight > 0 && (
                        <span className="ml-2 text-xs text-slate-400">unknown portion not penalized</span>
                      )}
                    </span>
                    <span className="tabular-nums text-slate-900">
                      {c.earned} / {c.weight}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="mt-3">
              <SectionTitle>Evidence</SectionTitle>
              <ul className="space-y-1 text-sm">
                {Array.isArray(match.evidence) &&
                  match.evidence.map((row, i) => {
                    const e = row as { requirement?: string; status?: string; explanation?: string };
                    return (
                      <li key={i} className="text-slate-700">
                        <Chip>{e.status}</Chip> <b>{e.requirement}</b> — {e.explanation}
                      </li>
                    );
                  })}
              </ul>
            </div>
          </Card>
        )}
      </div>
    );
  }

  if (page === null) return <Spinner />;

  return (
    <div className="space-y-4">
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void loadList(query);
        }}
      >
        <input
          className="w-full rounded border border-slate-300 px-3 py-2 text-sm"
          placeholder="Search title or description…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Search
        </button>
      </form>
      {error && <p className="text-rose-700">{error}</p>}
      <p className="text-sm text-slate-500">{page.total} jobs. Every job stays listed.</p>
      {page.items.map((job) => (
        <Card key={job.id} className="hover:border-slate-300">
          <button className="text-left" onClick={() => onSelectJob(job.id)}>
            <span className="font-semibold text-slate-900 underline-offset-2 hover:underline">
              {job.title}
            </span>
            <p className="text-sm text-slate-600">{job.company ?? "—"}</p>
            <p className="mt-1 text-xs text-slate-500">
              {[job.location, job.employment_type, job.is_remote ? "remote" : null]
                .filter(Boolean)
                .join(" · ") || "—"}
              {job.salary_max ? ` · ${job.salary_min ?? "?"}–${job.salary_max} ${job.salary_currency ?? ""}` : ""}
              {job.posted_at ? ` · posted ${job.posted_at.slice(0, 10)}` : ""}
            </p>
          </button>
        </Card>
      ))}
    </div>
  );
}
