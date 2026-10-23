"""Schemas for the truthful CV tailoring pipeline.

Every produced claim must carry `evidence_refs` pointing at source content
in the original CV (e.g. `exp[0].bullets[1]`, `skill[2]`, `proj[3]`).
Claims failing validation are reported in `unsupported_claims`; validation
is deterministic Python, never the LLM.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SectionName = Literal["experiences", "education", "skills", "projects", "certifications"]

_EVIDENCE_PREFIXES = ("exp[", "proj[", "skill[", "cert[", "edu[")


class TailoredBullet(BaseModel):
    """One proposed bullet; must reference original CV content."""

    text: str = Field(min_length=1, max_length=600)
    evidence_refs: list[str] = Field(min_length=1)

    @field_validator("evidence_refs", mode="after")
    @classmethod
    def refs_must_point_into_cv(cls, refs: list[str]) -> list[str]:
        cleaned = [r.strip() for r in refs if r.strip()]
        if not all(r.startswith(_EVIDENCE_PREFIXES) for r in cleaned):
            raise ValueError("evidence_refs must use exp[i]/proj[i]/skill[i]/cert[i]/edu[i] forms")
        return cleaned


class TailoredSection(BaseModel):
    """A generated CV section with per-bullet provenance."""

    name: str
    items: list[TailoredBullet] = Field(default_factory=list)


class TailoredContent(BaseModel):
    """Proposed CV document content (JSONB in tailored_resumes.content)."""

    title: str | None = None
    sections: list[TailoredSection] = Field(default_factory=list)

    @property
    def all_bullets(self) -> list[TailoredBullet]:
        return [b for s in self.sections for b in s.items]


class ChangeSummary(BaseModel):
    """Diff-style summary of what the tailoring changed and what it dropped."""

    reworded_bullets: int = 0
    added_sections: list[str] = Field(default_factory=list)
    removed_sections: list[str] = Field(default_factory=list)
    dropped_bullets: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class UnsupportedClaim(BaseModel):
    """A generated claim rejected by deterministic validation."""

    section: str
    text: str
    reason: str
    evidence_refs: list[str] = Field(default_factory=list)
