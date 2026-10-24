import { useCallback, useEffect, useMemo, useState } from "react";
import { api, applicationsApi, ApiError } from "../api";
import type { ApplicationRow, ApplicationsBoard, Job, JobsPage, TailoredResume } from "../types";
import { Card, Chip, SectionTitle, Spinner } from "../components/ui";

const APPROVAL_STYLES: Record<string, string> = {
  draft: "bg-slate-100 text-slate-700",
  pending_review: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-700",
};

const STATUS_LABELS: Record<string, string> = {
  queued: "Queued",
  prepared: "Ready",
  submitted: "Submitted",
  interviewing: "Interview",
  assessment: "Assessment",
  offer: "Offer",
  rejected: "Rejected",
  withdrawn: "Withdrawn",
  closed: "Closed",
};

function jobDetailText(job: Job): string {
  const lines = [
    "Job: " + job.title,
    job.company ? "Company: " + job.company : null,
    job.location ? "Location: " + job.location : null,
    "Official URL: " + job.canonical_url,
    "",
    job.description ?? "",
  ];
  return lines.filter((l) => l !== null).join("\n");
}

function resumeText(target: TailoredResume): string {
  const blocks: string[] = [];
  if (target.content.title) blocks.push(target.content.title);
  for (const section of target.content.sections) {
    blocks.push("", section.name);
    for (const bullet of section.items) {
      blocks.push(
        bullet.evidence_refs.length ? `- ${bullet.text}   [${bullet.evidence_refs.join("; ")}]` : `- ${bullet.text}`,
      );
    }
  }
  return blocks.join("\n").trim();
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export default function AssistedApply({ onNavigate }: { onNavigate: (target: "applications" | "tailored") => void }) {
  const [jobs, setJobs] = useState<JobsPage | null>(null);
  const [board, setBoard] = useState<ApplicationsBoard | null>(null);
  const [tailored, setTailored] = useState<TailoredResume[] | null>(null);
  const [jobId, setJobId] = useState("");
  const [resumeId, setResumeId] = useState("");
  const [result, setResult] = useState<ApplicationRow | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [jobPage, applications, tailoredRows] = await Promise.all([
        api.get<JobsPage>("/jobs"),
        applicationsApi.board(),
        api.get<TailoredResume[]>("/tailored"),
      ]);
      setJobs(jobPage);
      setBoard(applications);
      setTailored(tailoredRows);
    } catch (exc) {
      setError(exc instanceof ApiError ? `${exc.status}: ${exc.message}` : "Failed to load data");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // Changing the job invalidates the previously selected resume.
  useEffect(() => {
    setResumeId("");
  }, [jobId]);

  const selectedJob = useMemo(() => jobs?.items.find((j) => j.id === jobId) ?? null, [jobs, jobId]);
  const matchingResumes = useMemo(
    () => (tailored ?? []).filter((t) => t.job_id === jobId),
    [tailored, jobId],
  );
  const selectedResume = useMemo(
    () => matchingResumes.find((t) => t.id === resumeId) ?? null,
    [matchingResumes, resumeId],
  );
  const existingApplication = useMemo(
    () => (board?.items.find((a) => a.job_id === jobId) ?? null),
    [board, jobId],
  );

  async function createOrReuse() {
    if (!jobId) {
      setError("Choose a job first.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const row = await applicationsApi.create(jobId, resumeId || undefined);
      setResult(row);
      setNotice(
        "Assisted apply completed — nothing has been submitted anywhere. " +
          "The application is only marked submitted when you explicitly confirm in Application tracking.",
      );
    } catch (exc) {
      setError(exc instanceof ApiError ? `${exc.status}: ${exc.message}` : "Failed to create the application");
    } finally {
      setBusy(false);
    }
  }

  async function copy(kind: "job" | "resume") {
    const text = kind === "job" && selectedJob ? jobDetailText(selectedJob) : selectedResume ? resumeText(selectedResume) : null;
    if (!text) return;
    const ok = await copyToClipboard(text);
    setNotice(ok ? "Copied to clipboard." : "Copy failed — your browser blocked clipboard access.");
  }

  if (jobs === null || tailored === null) {
    if (error) {
      return <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>;
    }
    return <Spinner />;
  }

  return (
    <div className="space-y-4">
      {error && <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}
      {notice && <div className="rounded border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">{notice}</div>}

      <Card data-testid="apply-picker">
        <SectionTitle>1 · Pick a job</SectionTitle>
        <select
          aria-label="Choose a job"
          data-testid="apply-job-select"
          className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
          value={jobId}
          onChange={(e) => {
            setJobId(e.target.value);
            setError(null);
            setResult(null);
            setNotice(null);
          }}
        >
          <option value="">— choose a job —</option>
          {jobs.items.map((j: Job) => (
            <option key={j.id} value={j.id}>
              {j.title} @ {j.company ?? "?"}
              {j.is_expired ? " (listing expired)" : ""}
            </option>
          ))}
        </select>
        {jobs.items.length === 0 && (
          <p className="mt-2 text-sm text-slate-500">No jobs stored yet — ingest from the Matches tab first.</p>
        )}
        {existingApplication && (
          <p className="mt-2 text-sm text-slate-600" data-testid="already-tracked">
            This job is already tracked in Application tracking (status:{" "}
            {STATUS_LABELS[existingApplication.status] ?? existingApplication.status}). Creating again reuses the
            same record.
          </p>
        )}

        <SectionTitle>2 · Pick the tailored CV for this job</SectionTitle>
        {matchingResumes.length === 0 ? (
          <p className="text-sm text-amber-700" data-testid="no-tailored-warning">
            No tailored CV exists for this job yet — create one in the Tailored CV tab, or continue without one.
            <button
              className="ml-2 rounded border border-slate-300 px-2 py-1 text-xs font-medium hover:bg-slate-50"
              onClick={() => onNavigate("tailored")}
            >
              Go to Tailored CV
            </button>
          </p>
        ) : (
          <select
            aria-label="Choose a tailored CV"
            data-testid="apply-resume-select"
            className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
            value={resumeId}
            onChange={(e) => setResumeId(e.target.value)}
          >
            <option value="">— none (track without a selected CV) —</option>
            {matchingResumes.map((t) => (
              <option key={t.id} value={t.id}>
                Tailored CV v{t.version} · {t.approval_status}
              </option>
            ))}
          </select>
        )}

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className="rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
            onClick={() => void createOrReuse()}
            disabled={busy || !jobId}
            data-testid="apply-create"
          >
            {existingApplication ? "Reuse tracking record" : "Create tracking record"}
          </button>
        </div>
      </Card>

      {selectedJob && (
        <Card data-testid="apply-job-review">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <SectionTitle>3 · Review the job</SectionTitle>
              <p className="font-semibold text-slate-900">{selectedJob.title}</p>
              <p className="text-sm text-slate-600">
                {[selectedJob.company, selectedJob.location].filter(Boolean).join(" · ") || "—"}
              </p>
              {selectedJob.is_expired && <Chip tone="rose">Listing expired</Chip>}
              <a className="mt-1 block text-xs text-sky-700 underline" href={selectedJob.canonical_url} target="_blank" rel="noreferrer">
                Official application URL
              </a>
            </div>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
              onClick={() => void copy("job")}
            >
              Copy job details
            </button>
          </div>
          {selectedJob.description && (
            <p className="mt-2 max-h-40 overflow-y-auto whitespace-pre-wrap text-sm text-slate-700">
              {selectedJob.description.slice(0, 1200)}
              {selectedJob.description.length > 1200 ? "…" : ""}
            </p>
          )}
        </Card>
      )}

      {selectedResume && (
        <Card data-testid="apply-resume-review">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <SectionTitle>4 · Review your tailored CV</SectionTitle>
              <p className="text-sm text-slate-600">
                v{selectedResume.version}{" "}
                <span className={`ml-1 rounded px-1.5 py-0.5 text-xs font-semibold ${APPROVAL_STYLES[selectedResume.approval_status] ?? ""}`}>
                  {selectedResume.approval_status}
                </span>
              </p>
            </div>
            <button
              className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
              onClick={() => void copy("resume")}
            >
              Copy CV content
            </button>
          </div>
          {selectedResume.unsupported_claims.length > 0 && (
            <div className="mt-2 rounded border border-amber-300 bg-amber-50 p-3" data-testid="apply-unsupported-claims">
              <SectionTitle>Unsupported claims ({selectedResume.unsupported_claims.length}) — kept out of the CV</SectionTitle>
              <ul className="list-inside list-disc space-y-1 text-sm text-amber-900">
                {selectedResume.unsupported_claims.map((c, i) => (
                  <li key={i}>
                    <Chip tone="rose">{c.section}</Chip> “{c.text}” — {c.reason}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="mt-2">
            {selectedResume.content.sections.map((section) => (
              <div key={section.name} className="mb-3">
                <SectionTitle>{section.name}</SectionTitle>
                <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
                  {section.items.map((b, i) => (
                    <li key={i}>
                      {b.text}
                      {b.evidence_refs.length > 0 && (
                        <span className="ml-2 text-xs text-slate-400">evidence: {b.evidence_refs.join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}

      {result && (
        <Card data-testid="apply-result">
          <SectionTitle>Tracking record ready</SectionTitle>
          <p className="text-sm text-slate-700">
            Current status: <b>{STATUS_LABELS[result.status] ?? result.status}</b>
            {result.tailored_resume_id ? " · tailored CV attached" : ""}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Nothing was submitted to the employer. Use “I applied” in Application tracking after you submit externally.
          </p>
          <button
            className="mt-3 rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-700"
            onClick={() => onNavigate("applications")}
            data-testid="apply-open-tracking"
          >
            Open application tracking
          </button>
        </Card>
      )}
    </div>
  );
}
