import type { ReactNode } from "react";
import type { Tier } from "../types";

const TIER_STYLES: Record<Tier, string> = {
  strong: "bg-emerald-100 text-emerald-800 border-emerald-300",
  good: "bg-sky-100 text-sky-800 border-sky-300",
  stretch: "bg-amber-100 text-amber-800 border-amber-300",
  long_shot: "bg-slate-100 text-slate-600 border-slate-300",
};

export function TierBadge({ tier }: { tier: Tier }) {
  return (
    <span
      className={`inline-block rounded border px-2 py-0.5 text-xs font-semibold ${TIER_STYLES[tier] ?? TIER_STYLES.long_shot}`}
    >
      {tier.replace("_", " ")}
    </span>
  );
}

export function ScoreBadge({ score }: { score: number }) {
  return (
    <span className="inline-flex items-center justify-center rounded-full bg-slate-900 px-2.5 py-0.5 text-sm font-bold text-white tabular-nums">
      {score}
    </span>
  );
}

export function Chip({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "amber" | "rose" }) {
  const styles = {
    slate: "bg-slate-100 text-slate-700",
    amber: "bg-amber-100 text-amber-800",
    rose: "bg-rose-100 text-rose-800",
  }[tone];
  return <span className={`inline-block rounded px-2 py-0.5 text-xs ${styles}`}>{children}</span>;
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-lg border border-slate-200 bg-white p-4 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">{children}</h3>;
}

export function Spinner() {
  return <div className="py-8 text-center text-sm text-slate-500">Loading…</div>;
}
