import { useCallback, useEffect, useMemo, useState } from "react";
import { applicationsApi, ApiError } from "../api";
import type { ApplicationRow, ApplicationStatus, ApplicationsBoard, AvailabilityInfo, ApplicationEventRow } from "../types";
import { Card, Chip, SectionTitle, Spinner } from "../components/ui";

const STATUS_ORDER: ApplicationStatus[] = [
  "queued",
  "prepared",
  "submitted",
  "interviewing",
  "assessment",
  "offer",
  "rejected",
  "withdrawn",
  "closed",
];

const STATUS_LABELS: Record<ApplicationStatus, string> = {
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

const STATUS_TONE: Record<ApplicationStatus, "slate" | "amber" | "rose"> = {
  queued: "slate",
  prepared: "amber",
  submitted: "slate",
  interviewing: "amber",
  assessment: "amber",
  offer: "slate",
  rejected: "rose",
  withdrawn: "rose",
  closed: "rose",
};

type AvailabilityCache = Record<string, AvailabilityInfo>;

export default function Applications() {
  const [board, setBoard] = useState<ApplicationsBoard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | ApplicationStatus>("all");
  const [sort, setSort] = useState<"updated" | "status">("updated");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [events, setEvents] = useState<Record<string, ApplicationEventRow[]>>({});
  const [availability, setAvailability] = useState<AvailabilityCache>({});

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setBoard(await applicationsApi.board());
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Failed to load applications");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const items = useMemo(() => {
    if (!board) return [];
    const q = search.trim().toLowerCase();
    let rows = board.items;
    if (q) {
      rows = rows.filter(
        (a) =>
          (a.job_company ?? "").toLowerCase().includes(q) ||
          (a.job_title ?? "").toLowerCase().includes(q),
      );
    }
    if (statusFilter !== "all") rows = rows.filter((a) => a.status === statusFilter);
    rows = [...rows].sort((a, b) => {
      if (sort === "status") {
        return (
          STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
          (b.updated_at ?? "").localeCompare(a.updated_at ?? "")
        );
      }
      return (b.updated_at ?? "").localeCompare(a.updated_at ?? "");
    });
    return rows;
  }, [board, search, statusFilter, sort]);

  async function act(id: string, fn: () => Promise<ApplicationRow>) {
    setBusyId(id);
    setError(null);
    try {
      const updated = await fn();
      setBoard(
        (prev) => prev && {
          ...prev,
          items: prev.items.map((a) => (a.id === id ? updated : a)),
          counts: {
            ...prev.counts,
            [updated.status]: (prev.counts[updated.status] ?? 0) + 1,
          },
        },
      );
      const evs = await applicationsApi.events(id);
      setEvents((prev) => ({ ...prev, [id]: evs }));
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Action failed");
    } finally {
      setBusyId(null);
    }
  }

  async function openDetail(id: string) {
    setOpenId((cur) => (cur === id ? null : id));
    if (openId === id) return;
    try {
      const evs = await applicationsApi.events(id);
      setEvents((prev) => ({ ...prev, [id]: evs }));
    } catch {
      // timeline stays empty; error banner reports API problems
    }
  }

  async function recheckAvailability(id: string) {
    setBusyId(id);
    setError(null);
    try {
      const info = await applicationsApi.availability(id);
      setAvailability((prev) => ({ ...prev, [id]: info }));
    } catch (e) {
      setError(e instanceof ApiError ? `${e.status}: ${e.message}` : "Availability check failed");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) return <Spinner />;
  if (error && !board) return <div className="rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>;

  const canConfirmSubmit = (a: ApplicationRow) =>
    (a.status === "queued" || a.status === "prepared") && !a.submitted_at;

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center gap-2" data-testid="app-board-controls">
        <input
          className="w-56 rounded border border-slate-300 px-2 py-1 text-sm"
          placeholder="Search company or title…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Search applications"
        />
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          aria-label="Filter by status"
        >
          <option value="all">All statuses</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_LABELS[s]}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-slate-300 px-2 py-1 text-sm"
          value={sort}
          onChange={(e) => setSort(e.target.value as typeof sort)}
          aria-label="Sort"
        >
          <option value="updated">Sort by date</option>
          <option value="status">Sort by status</option>
        </select>
      </div>

      {error && <div className="mb-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">{error}</div>}

      {items.length === 0 ? (
        <div className="rounded border border-slate-200 bg-white p-6 text-center text-sm text-slate-500">
          <p className="font-medium text-slate-600">No applications yet</p>
          <p className="mt-1">Prepare an application from the Jobs or Matches tab.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((a) => {
            const info = availability[a.id];
            const isOpenDetail = openId === a.id;
            return (
              <Card key={a.id} data-testid={`application-${a.id}`}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="font-semibold text-slate-900">
                      {a.job_company ?? "Unknown company"} — {a.job_title ?? "Unknown title"}
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <Chip tone={STATUS_TONE[a.status]}>{STATUS_LABELS[a.status]}</Chip>
                      {a.job_is_active === false && <Chip tone="rose">Listing inactive</Chip>}
                      {a.submitted_at && <span>Submitted {a.submitted_at.slice(0, 10)}</span>}
                      <span>Updated {a.updated_at?.slice(0, 10) ?? "—"}</span>
                    </div>
                    {info && a.status !== "closed" && a.status !== "withdrawn" && (
                      <div className="mt-2 text-xs" data-testid={`availability-${a.id}`}>
                        {info.outcome === "closed" && (
                          <span className="text-rose-700">Listing appears closed — {info.reason}</span>
                        )}
                        {info.outcome === "unknown" && (
                          <span className="text-amber-700">Availability cannot be verified — {info.reason}</span>
                        )}
                        {info.outcome === "open" && <span className="text-emerald-700">Listing open at the source</span>}
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canConfirmSubmit(a) && (
                      <button
                        className="rounded bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-700 disabled:opacity-50"
                        disabled={busyId === a.id}
                        onClick={() => void act(a.id, () => applicationsApi.confirmSubmit(a.id))}
                        data-testid={`confirm-submit-${a.id}`}
                      >
                        I applied
                      </button>
                    )}
                    <select
                      className="rounded border border-slate-300 px-2 py-1 text-xs"
                      value=""
                      aria-label="Change status"
                      disabled={busyId === a.id || a.allowed_transitions.length === 0}
                      onChange={(e) => {
                        const target = e.target.value;
                        e.target.value = "";
                        if (target) void act(a.id, () => applicationsApi.setStatus(a.id, target as ApplicationStatus));
                      }}
                    >
                      <option value="">Move to…</option>
                      {a.allowed_transitions.map((s) => (
                        <option key={s} value={s}>
                          {STATUS_LABELS[s] ?? s}
                        </option>
                      ))}
                    </select>
                    <button
                      className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
                      disabled={busyId === a.id}
                      onClick={() => void recheckAvailability(a.id)}
                    >
                      Check availability
                    </button>
                    <button
                      className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                      onClick={() => void openDetail(a.id)}
                      aria-expanded={isOpenDetail}
                    >
                      {isOpenDetail ? "Hide details" : "Details"}
                    </button>
                  </div>
                </div>

                {isOpenDetail && (
                  <div className="mt-4 border-t border-slate-100 pt-3">
                    {a.job_canonical_url && (
                      <p className="mb-2 text-xs text-slate-500">
                        Official application link:{" "}
                        <a
                          className="text-sky-700 underline"
                          href={a.job_canonical_url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {a.job_canonical_url}
                        </a>
                      </p>
                    )}
                    <SectionTitle>Event timeline</SectionTitle>
                    {(events[a.id] ?? []).length === 0 ? (
                      <p className="text-xs text-slate-500">No events recorded.</p>
                    ) : (
                      <ol className="space-y-2">
                        {(events[a.id] ?? []).map((ev) => (
                          <li key={ev.id} className="text-xs text-slate-700" data-testid={`event-${ev.id}`}>
                            <span className="font-semibold">{ev.event_type.replace(/_/g, " ")}</span>{" "}
                            <span className="text-slate-400">{ev.occurred_at.replace("T", " ").slice(0, 16)}</span>
                            {typeof ev.payload?.previous_status === "string" &&
                              typeof ev.payload?.new_status === "string" && (
                                <span className="ml-2">
                                  {STATUS_LABELS[ev.payload.previous_status as ApplicationStatus] ?? ev.payload.previous_status}
                                  {" → "}
                                  {STATUS_LABELS[ev.payload.new_status as ApplicationStatus] ?? ev.payload.new_status}
                                </span>
                              )}
                            {typeof ev.payload?.notes === "string" && (
                              <span className="block text-slate-500">“{ev.payload.notes as string}”</span>
                            )}
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </Card>
            );
          })}
        </div>
      )}
    </section>
  );
}
