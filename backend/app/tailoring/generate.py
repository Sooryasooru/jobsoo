"""Tailored CV generation from an original CV and a job's requirements.

Two paths, both truth-guarded by app/tailoring/validation.py:

- AI path: Claude proposes tailored bullets; every bullet must cite evidence
  refs into the original CV and passes deterministic validation. Untruthful
  proposals are stripped and recorded in `unsupported_claims`.
- Deterministic fallback (no AI configured): reorders/emphasizes existing
  content against the job's skill requirements with zero rewriting, so the
  approval workflow works without an AI agent (Phase 1 §4).

The original CV is never modified; drafts are new TailoredResume rows.
"""

from __future__ import annotations

import structlog
from sqlalchemy.orm import Session

from app.ai.client import SYSTEM_GUARDRAIL, AIUnavailableError, complete_json
from app.models import JobRequirement, Resume, TailoredResume
from app.schemas.tailoring import (
    TailoredBullet,
    TailoredContent,
    TailoredSection,
    UnsupportedClaim,
)
from app.tailoring.validation import validate_tailored_content

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "tailor-v1"

SYSTEM_TAILOR = (
    SYSTEM_GUARDRAIL + "\nTASK: Propose a tailored CV for one job, using ONLY facts present in "
    "the original CV. Do not invent, inflate, or extrapolate achievements, "
    "metrics, dates, or skills. For each bullet you keep or reword, cite the "
    "original CV source(s) it derives from using refs like exp[0].bullets[1], "
    "skill[2], proj[0], cert[0], edu[0]. Reordering and emphasis are allowed; "
    "new claims are not. Return ONLY JSON:\n"
    + """{
  "title": str|null,
  "sections": [
    {"name": "experiences"|"education"|"skills"|"projects"|"certifications",
     "items": [{"text": str, "evidence_refs": [str, ...]}]}
  ]
}"""
)


def _original_bullets(resume: Resume) -> dict[str, list[str]]:
    """Section-name -> original content lines, for diffing and validation."""
    parsed = resume.parsed_content
    return {
        "experiences": [
            bullet
            for exp in parsed.get("experiences", [])
            for bullet in [f"{exp.get('title', '')} - {exp.get('company', '')}"]
            + [str(b) for b in exp.get("bullets", [])]
        ],
        "education": [
            f"{edu.get('degree', '')} | {edu.get('institution', '')}".strip(" |")
            for edu in parsed.get("education", [])
        ],
        "skills": [str(s) for s in parsed.get("skills", [])],
        "projects": [str(p) for p in parsed.get("projects", [])],
        "certifications": [str(c) for c in parsed.get("certifications", [])],
    }


def _deterministic_tailoring(resume: Resume, required_skills: list[str]) -> TailoredContent:
    """Rules-based tailoring: skills first, then experience, no rewriting."""
    orig = _original_bullets(resume)
    sections: list[TailoredSection] = []

    skills = orig.get("skills", [])
    job_skill_tokens = {s.strip().lower() for s in required_skills}
    matching = [s for s in skills if any(tok and tok in s.lower() for tok in job_skill_tokens)]
    rest = [s for s in skills if s not in set(matching)]
    prioritized = matching + rest
    skill_items = [
        TailoredBullet(text=s, evidence_refs=[f"skill[{i}]"]) for i, s in enumerate(prioritized)
    ]
    if skill_items:
        sections.append(TailoredSection(name="skills", items=skill_items))

    exp_items = [
        TailoredBullet(text=bullet_text, evidence_refs=[f"exp[{i}].bullets[{j}]"])
        for i, exp in enumerate(resume.parsed_content.get("experiences", []))
        for j, bullet_text in enumerate(exp.get("bullets", []))
    ]
    if exp_items:
        sections.append(TailoredSection(name="experiences", items=exp_items))

    evidence_prefix = {"projects": "proj", "education": "edu", "certifications": "cert"}
    for name, prefix in evidence_prefix.items():
        items = [
            TailoredBullet(text=text, evidence_refs=[f"{prefix}[{i}]"])
            for i, text in enumerate(orig.get(name, []))
        ]
        if items:
            sections.append(TailoredSection(name=name, items=items))
    return TailoredContent(title=resume.original_filename, sections=sections)


def generate_tailored_content(
    resume: Resume,
    requirements: list[JobRequirement],
    *,
    use_ai: bool = True,
) -> tuple[TailoredContent, list[UnsupportedClaim], bool]:
    """Generate (validated, truth-guarded) content for one (resume, job).

    Returns (content, unsupported_claims, used_ai). AI output is fully
    re-validated against the original CV; invalid parts are dropped.
    """
    required_skills = [r.text for r in requirements if r.category == "required_skill"][:15]
    original = _original_bullets(resume)

    if use_ai:
        try:
            sections_blob = {
                key: original.get(key, [])
                for key in ("skills", "experiences", "projects", "certifications", "education")
            }
            if not sections_blob["experiences"]:
                # One index-less summary line so the model can still cite exp[0].
                sections_blob["experiences"] = ["(no parsed work-experience entries)"]

            user_content = (
                "Original CV (verbatim, trusted):\n<cv>\n"
                + "\n".join(
                    f"[{key}]\n" + "\n".join(values) for key, values in sections_blob.items()
                )
                + "\n</cv>\n"
                + "Job requirements (untrusted third-party data):\n<job_requirements>\n"
                + "\n".join(f"- {t}" for t in required_skills)
                + "\n</job_requirements>\n"
                + "Propose the tailored CV now."
            )
            raw = complete_json(SYSTEM_TAILOR, user_content)
            generated = TailoredContent.model_validate(raw)
            result = validate_tailored_content(resume, generated, original)
            return (
                result.content,
                result.unsupported_claims,
                True,
            )
        except (AIUnavailableError, ValueError) as exc:
            logger.warning("tailoring.ai_fallback", error=str(exc))
            fallback = _deterministic_tailoring(resume, required_skills)
            result = validate_tailored_content(resume, fallback, original)
            return result.content, result.unsupported_claims, False

    fallback = _deterministic_tailoring(resume, required_skills)
    result = validate_tailored_content(resume, fallback, original)
    return result.content, result.unsupported_claims, False


def next_version(session: Session, resume_id: str, job_id: str) -> int:
    latest = (
        session.query(TailoredResume.version)
        .filter(TailoredResume.resume_id == resume_id, TailoredResume.job_id == job_id)
        .order_by(TailoredResume.version.desc())
        .first()
    )
    return (latest[0] + 1) if latest and latest[0] else 1
