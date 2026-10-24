// Types mirroring the FastAPI response payloads.

export type Tier = "strong" | "good" | "stretch" | "long_shot";

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
}

export type ApplicationStatus =
  | "queued"
  | "prepared"
  | "submitted"
  | "interviewing"
  | "assessment"
  | "rejected"
  | "offer"
  | "withdrawn"
  | "closed";

export interface ApplicationRow {
  id: string;
  job_id: string;
  status: ApplicationStatus;
  notes: string | null;
  submitted_at: string | null;
  tailored_resume_id: string | null;
  created_at: string | null;
  updated_at: string | null;
  job_title: string | null;
  job_company: string | null;
  job_canonical_url: string | null;
  job_is_active: boolean | null;
  job_is_expired: boolean | null;
  job_source: string | null;
  allowed_transitions: ApplicationStatus[];
}

export interface ApplicationEventRow {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
  created_at: string | null;
}

export interface ApplicationsBoard {
  items: ApplicationRow[];
  counts: Record<string, number>;
}

export interface AvailabilityInfo {
  outcome: "open" | "closed" | "unknown";
  reason: string;
}

export interface Job {
  id: string;
  source: string;
  source_job_id: string;
  title: string;
  company: string | null;
  location: string | null;
  description: string | null;
  employment_type: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  is_remote: boolean | null;
  remote_policy: string | null;
  canonical_url: string;
  original_url: string;
  posted_at: string | null;
  is_active: boolean;
  is_expired: boolean;
}

export interface JobsPage {
  total: number;
  items: Job[];
}

export interface IngestStats {
  total: number;
  active: number;
  expired: number;
  by_source: Record<string, number>;
}

export interface IngestResult {
  inserted: number;
  updated: number;
  flagged_possible_duplicates: number;
  inactive_count: number;
  total_seen: number;
}

export interface MatchPayload {
  job_id: string;
  user_id: string;
  score: number;
  tier: Tier;
  recommendation: string;
  explanation: Record<string, unknown> | string | null;
  score_components: ScoreComponent[];
  matched_skills: string[];
  missing_skills: string[];
  unknown_skills: string[];
  evidence: unknown[];
  hard_blocker_warnings: string[];
  unknown_requirements: string[];
  experience_gap_years: number | null;
  scoring_rules_version: string;
  computed_at: string | null;
  job_title?: string | null;
  job_company?: string | null;
  job_location?: string | null;
}

export interface ScoreComponent {
  name: string;
  earned: number;
  weight: number;
  unknown_weight: number;
  detail: string;
}

export interface ScoringRules {
  version: string;
  rules: Record<string, ScoreComponent>;
}

export interface RequirementRow {
  id: string;
  category: string;
  text: string;
  is_required: boolean;
  is_hard_blocker: boolean;
  min_years: number | null;
  extraction_meta: Record<string, unknown>;
}

export interface ExtractionResult {
  job_id: string;
  from_cache: boolean;
  extraction: {
    job_title: string | null;
    company: string | null;
    location: string | null;
    employment_type: string | null;
    remote_policy: string | null;
    required_skills: { text: string }[];
    preferred_skills: { text: string }[];
    min_professional_years: number | null;
    education: string[];
    certifications: string[];
    work_authorization: string | null;
    unknown_fields: string[];
    ambiguity_notes: string[];
  };
  evidence_report: {
    unknown_fields: string[];
    evidence: { requirement: string; category?: string; status: string; explanation: string }[];
  };
}

export interface Resume {
  id: string;
  kind: string;
  original_filename: string;
  file_type: string;
  file_size_bytes: number;
  parsed_content: Record<string, unknown>;
  parse_notes: string[];
  created_at: string;
}

export interface Profile {
  full_name: string;
  location: string;
  headline: string;
  professional_experience_years: number | null;
  skills: string[];
  preferred_locations: string[];
  remote_preference: string;
  expected_salary_min: number | null;
  expected_salary_currency: string | null;
  work_rights: string;
  career_start_date: string | null;
}

export interface TailoredBullet {
  text: string;
  evidence_refs: string[];
}

export interface TailoredSection {
  name: string;
  items: TailoredBullet[];
}

export interface UnsupportedClaim {
  section: string;
  text: string;
  reason: string;
  evidence_refs: string[];
}

export interface TailoredResume {
  id: string;
  resume_id: string;
  job_id: string;
  version: number;
  approval_status: "draft" | "pending_review" | "approved" | "rejected";
  content: { title: string | null; sections: TailoredSection[] };
  unsupported_claims: UnsupportedClaim[];
  final_pdf_path: string | null;
  approved_at: string | null;
  created_at: string;
}

export interface JobRefs {
  [jobId: string]: { title: string; company: string | null };
}
