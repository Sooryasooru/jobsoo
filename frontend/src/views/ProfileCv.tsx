import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { Card, SectionTitle, Spinner } from "../components/ui";
import type { Profile, Resume } from "../types";

export default function ProfileCv({
  sourceCvId,
  onSelectCv,
}: {
  sourceCvId: string | null;
  onSelectCv: (cvId: string | null) => void;
}) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [cvs, setCvs] = useState<Resume[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [skillsText, setSkillsText] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const [p, list] = await Promise.all([api.get<Profile>("/profile"), api.get<Resume[]>("/cvs")]);
      setProfile(p);
      setCvs(list);
      setSkillsText(p.skills.join(", "));
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to load profile");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const saveProfile = async () => {
    if (!profile) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.put<Profile>("/profile", {
        full_name: profile.full_name || null,
        location: profile.location || null,
        headline: profile.headline || null,
        professional_experience_years: profile.professional_experience_years,
        skills: skillsText
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        preferred_locations: profile.preferred_locations,
        remote_preference: profile.remote_preference || null,
        expected_salary_min: profile.expected_salary_min,
        expected_salary_currency: profile.expected_salary_currency,
        work_rights: profile.work_rights || null,
        career_start_date: profile.career_start_date,
      });
      setProfile(updated);
      setSkillsText(updated.skills.join(", "));
      setNotice("Profile saved.");
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "failed to save profile");
    } finally {
      setBusy(false);
    }
  };

  const uploadCv = async (file: File) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.uploadCv(file);
      onSelectCv(result.id);
      setNotice(
        `CV parsed: ${result.original_filename}` +
          (result.parse_notes?.length ? ` (notes: ${result.parse_notes.join("; ")})` : ""),
      );
      await load();
    } catch (exc) {
      setError(exc instanceof ApiError ? exc.message : "upload failed");
    } finally {
      setBusy(false);
    }
  };

  if (profile === null) return <Spinner />;

  return (
    <div className="space-y-4">
      {error && <p className="text-rose-700">{error}</p>}
      {notice && <p className="text-emerald-700">{notice}</p>}

      <Card>
        <SectionTitle>Candidate profile</SectionTitle>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-sm">
            <span className="text-slate-600">Full name</span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.full_name}
              onChange={(e) => setProfile({ ...profile, full_name: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-600">Location</span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.location}
              onChange={(e) => setProfile({ ...profile, location: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-600">Years of professional experience</span>
            <input
              type="number"
              min={0}
              step={0.5}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.professional_experience_years ?? ""}
              onChange={(e) =>
                setProfile({
                  ...profile,
                  professional_experience_years: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-600">Remote preference</span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.remote_preference}
              onChange={(e) => setProfile({ ...profile, remote_preference: e.target.value })}
            />
          </label>
          <label className="text-sm md:col-span-2">
            <span className="text-slate-600">
              Skills (comma-separated — anything you leave out stays unknown, never "lacking")
            </span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={skillsText}
              onChange={(e) => setSkillsText(e.target.value)}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-600">Work rights</span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.work_rights}
              onChange={(e) => setProfile({ ...profile, work_rights: e.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-slate-600">Career start date (ISO)</span>
            <input
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={profile.career_start_date ?? ""}
              onChange={(e) => setProfile({ ...profile, career_start_date: e.target.value })}
            />
          </label>
        </div>
        <button
          className="mt-3 rounded bg-slate-800 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
          onClick={() => void saveProfile()}
          disabled={busy}
        >
          Save profile
        </button>
      </Card>

      <Card>
        <SectionTitle>Original CVs (never modified)</SectionTitle>
        <input
          type="file"
          accept=".pdf,.docx,.md,.txt"
          className="text-sm"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void uploadCv(f);
          }}
          disabled={busy}
        />
        {cvs && cvs.length > 0 && (
          <ul className="mt-3 space-y-1 text-sm">
            {cvs.map((cv) => (
              <li key={cv.id}>
                <button
                  className={`rounded px-2 py-1 ${
                    sourceCvId === cv.id
                      ? "bg-emerald-600 text-white"
                      : "border border-slate-300 hover:bg-slate-50"
                  }`}
                  onClick={() => onSelectCv(cv.id)}
                  title="Select as the source CV for tailoring"
                >
                  {cv.original_filename} · {cv.file_type} · {(cv.file_size_bytes / 1024).toFixed(1)} KB
                  {cv.parse_notes?.length ? ` · ${cv.parse_notes.join(", ")}` : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
        {cvs &&
          (cvs.length === 0 ? (
            <p className="mt-2 text-xs text-slate-500">Upload a CV above to get started.</p>
          ) : (
            <p className="mt-2 text-xs text-slate-500">
              Select a CV (highlighted) to use as the tailoring source.
            </p>
          ))}
      </Card>
    </div>
  );
}
