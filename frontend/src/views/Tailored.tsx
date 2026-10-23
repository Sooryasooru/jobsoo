import { useCallback, useEffect, useState } from "react";
import { api, API_BASE, ApiError } from "../api";
import { Card, Chip, SectionTitle, Spinner } from "../components/ui";
import type { Job, JobsPage, TailoredResume } from "../types";

const STATUS_STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  pending_review: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-700",
};

export default function Tailored({ sourceCvId }: { sourceCvId: string | null }) {
  const [rows, setRows] = useState<TailoredResume[] | null>(null);
  const [jobs, setJobs] = useState<JobsPage | null>(null);
  const [targetJobId, setTargetJobId] = useState("");
  const [useAi, setUseAi] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [list, jobPage] = await Promise.all([
        api.get<TailoredResume[]>("/tailored"),
        api.get<JobsPage>("/jobs"),
      ]);
      setRows(list);
      setJobs(jobPage);
      if (!sourceCvId) {
        setNotice("Upload and select an original CV in the 'CV & Profile' tab to enable draft creation.");
      }
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to load tailored CVs");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createDraft = async () => {
    if (!sourceCvId || !targetJobId) {
      setError("Select an original CV (CV tab) and a target job first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const draft = await api.post<TailoredResume>(
        `/tailored?resume_id=${sourceCvId}&job_id=${targetJobId}&use_ai=${useAi}`,
      );
      await api.post(`/tailored/${draft.id}/submit`);
      setNotice(
        `Draft v${draft.version} created and submitted for review. ` +
          (draft.unsupported_claims.length
            ? `${draft.unsupported_claims.length} untruthful claim(s) were stripped — see below.`
            : "All claims validated against the original CV."),
      );
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to create draft");
    } finally {
      setBusy(false);
    }
  };

  const act = async (id: string, action: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.post(`/tailored/${id}/${action}`);
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "action failed");
    } finally {
      setBusy(false);
    }
  };

  if (rows === null) return <Spinner />;

  const jobLabel = (jobId: string) => {
    const job = jobs?.items.find((j) => j.id === jobId);
    return job ? `${job.title} @ ${job.company ?? "?"}` : jobId.slice(0, 8);
  };

  return (
    <div className="space-y-4">
      {error && <p className="text-rose-700">{error}</p>}
      {notice && <p className="text-emerald-700">{notice}</p>}

      <Card>
        <SectionTitle>Create a tailored draft</SectionTitle>
        {!sourceCvId && (
          <p className="mb-2 text-sm text-amber-700">
            No source CV selected — open the <b>CV & Profile</b> tab and select one.
          </p>
        )}
        <div className="flex flex-wrap items-end gap-3 text-sm">
          <label className="grow min-w-[16rem]">
            <span className="text-slate-600">Target job</span>
            <select
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={targetJobId}
              onChange={(e) => setTargetJobId(e.target.value)}
            >
              <option value="">— choose a job —</option>
              {jobs?.items.map((j: Job) => (
                <option key={j.id} value={j.id}>
                  {j.title} @ {j.company ?? "?"}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-slate-700">
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            Use AI tailoring (validated; falls back if unavailable)
          </label>
          <button
            className="rounded bg-slate-800 px-4 py-2 font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            onClick={() => void createDraft()}
            disabled={busy || !sourceCvId || !targetJobId}
          >
            Create draft
          </button>
        </div>
      </Card>

      {rows.map((row) => (
        <Card key={row.id}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <span
                className={`inline-block rounded px-2 py-0.5 text-xs font-semibold ${STATUS_STYLES[row.approval_status]}`}
              >
                {row.approval_status}
              </span>
              <span className="ml-2 text-sm text-slate-600">v{row.version}</span>
              <p className="mt-1 text-sm font-medium text-slate-800">→ {jobLabel(row.job_id)}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {row.approval_status === "pending_review" && (
                <>
                  <button
                    className="rounded bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                    onClick={() => void act(row.id, "approve")}
                    disabled={busy}
                  >
                    Approve (exports PDF)
                  </button>
                  <button
                    className="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
                    onClick={() => void act(row.id, "reject")}
                    disabled={busy}
                  >
                    Reject
                  </button>
                </>
              )}
              {row.approval_status === "draft" && (
                <button
                  className="rounded border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
                  onClick={() => void api.post(`/tailored/${row.id}/submit`).then(() => void load())}
                  disabled={busy}
                >
                  Submit for review
                </button>
              )}
              {row.approval_status === "approved" && (
                <a
                  className="rounded bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-500"
                  href={`${API_BASE}/tailored/${row.id}/pdf`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Download PDF
                </a>
              )}
            </div>
          </div>

          {row.unsupported_claims.length > 0 && (
            <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3">
              <SectionTitle>
                Stripped claims ({row.unsupported_claims.length}) — never applied to the CV
              </SectionTitle>
              <ul className="space-y-1 text-sm text-amber-900">
                {row.unsupported_claims.map((c, i) => (
                  <li key={i}>
                    <Chip tone="rose">{c.section}</Chip> “{c.text}” — {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-3">
            {row.content.sections.map((section) => (
              <div key={section.name} className="mb-3">
                <SectionTitle>{section.name}</SectionTitle>
                <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
                  {section.items.map((b, i) => (
                    <li key={i}>
                      {b.text}
                      <span className="ml-2 text-xs text-slate-400">{b.evidence_refs.join(", ")}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      ))}
    </div>
  );
}
