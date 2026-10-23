"""Deterministic validation of tailored CV claims against the original CV.

The LLM proposes; this module disposes. Every generated bullet must be
traceable to original CV content via evidence refs, and its text must
overlap the referenced source. Anything else is untruthful and is stripped.

No LLM is involved in validation (Phase 1 §12 truthfulness safeguards).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.models import Resume
from app.schemas.tailoring import (
    ChangeSummary,
    TailoredBullet,
    TailoredContent,
    UnsupportedClaim,
)

# A bullet is "supported" when this share of its content words appears in the
# referenced source text. Rephrasing is allowed; wholesale invention is not.
_OVERLAP_THRESHOLD = 0.6

_WORD_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9+#./-]*")
# Numbers (metrics, dates, years) that must exist verbatim in the source.
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?%?")


@dataclass
class ValidationResult:
    """Outcome of validating one generated draft."""

    content: TailoredContent
    unsupported_claims: list[UnsupportedClaim] = field(default_factory=list)
    change_summary: ChangeSummary = field(default_factory=ChangeSummary)

    @property
    def is_truthful(self) -> bool:
        return not self.unsupported_claims


def _content_words(text: str) -> set[str]:
    lowered = text.lower()
    words = {w.lower() for w in _WORD_RE.findall(lowered)}
    return words - {"the", "a", "an", "and", "or", "of", "in", "for", "to", "with", "at", "on"}


def _source_text(resume: Resume, index_in: str) -> str | None:
    """Resolve an evidence ref like `exp[0].bullets[1]` to original text."""
    match = re.fullmatch(r"(exp|proj|skill|cert|edu)\[(\d+)\](?:\.bullets\[(\d+)\])?", index_in)
    if match is None:
        return None
    kind, raw_idx, raw_bullet = match.group(1), int(match.group(2)), match.group(3)
    parsed = resume.parsed_content
    try:
        if kind == "exp":
            entry = parsed["experiences"][raw_idx]
            source_parts = [str(entry.get("title", "")), str(entry.get("company", ""))]
            if raw_bullet is not None:
                source_parts = [str(entry["bullets"][int(raw_bullet)])]
            else:
                source_parts += [str(b) for b in entry.get("bullets", [])]
            return " ".join(source_parts)
        if raw_bullet is not None:  # bullet refs only valid for experiences
            return None
        if kind == "proj":
            return str(parsed["projects"][raw_idx])
        if kind == "skill":
            return str(parsed["skills"][raw_idx])
        if kind == "cert":
            return str(parsed["certifications"][raw_idx])
        if kind == "edu":
            edu = parsed["education"][raw_idx]
            return " ".join(str(edu.get(k, "")) for k in ("degree", "institution", "year"))
    except (IndexError, KeyError, TypeError):
        return None
    return None


def _verify_bullet(
    bullet: TailoredBullet,
    section_name: str,
    resume: Resume,
) -> UnsupportedClaim | None:
    """Return an UnsupportedClaim when the bullet fails traceability."""
    sources: list[str] = []
    for ref in bullet.evidence_refs:
        text = _source_text(resume, ref)
        if text is None:
            return UnsupportedClaim(
                section=section_name,
                text=bullet.text,
                reason=f"evidence ref {ref!r} does not resolve to original CV content",
                evidence_refs=list(bullet.evidence_refs),
            )
        sources.append(text)

    bullet_words = _content_words(bullet.text)
    if not bullet_words:
        return UnsupportedClaim(
            section=section_name,
            text=bullet.text,
            reason="bullet has no verifiable content",
            evidence_refs=list(bullet.evidence_refs),
        )

    # Overlap against the union of referenced sources.
    source_words: set[str] = set()
    for text in sources:
        source_words |= _content_words(text)
    overlap = len(bullet_words & source_words) / len(bullet_words)
    if overlap < _OVERLAP_THRESHOLD:
        return UnsupportedClaim(
            section=section_name,
            text=bullet.text,
            reason=f"only {overlap:.0%} of bullet words appear in referenced CV content",
            evidence_refs=list(bullet.evidence_refs),
        )

    # Numbers must exist in a referenced source (guards invented metrics/dates).
    claimed_numbers = {m.replace(",", ".") for m in _NUMBER_RE.findall(bullet.text)}
    numbers_blob = " ".join(sources).replace(",", ".")
    invented = [n for n in claimed_numbers if n not in numbers_blob]
    if invented:
        return UnsupportedClaim(
            section=section_name,
            text=bullet.text,
            reason=f"numbers not present in the referenced CV content: {', '.join(invented)}",
            evidence_refs=list(bullet.evidence_refs),
        )
    return None


def validate_tailored_content(
    resume: Resume,
    generated: TailoredContent,
    original_bullets: dict[str, list[str]],
) -> ValidationResult:
    """Validate a generated draft; strips untruthful bullets.

    `original_bullets` maps section name -> original bullet texts from the
    original CV, used to attribute changed vs added vs removed content.
    """
    unsupported: list[UnsupportedClaim] = []
    kept_sections: list[Any] = []
    reworded_total = 0
    dropped_texts: list[str] = []

    for section in generated.sections:
        kept_items: list[TailoredBullet] = []
        for bullet in section.items:
            claim = _verify_bullet(bullet, section.name, resume)
            if claim is None:
                kept_items.append(bullet)
            else:
                unsupported.append(claim)
                dropped_texts.append(bullet.text)
        if kept_items:
            section.items = kept_items
            kept_sections.append(section)
            reworded_total += sum(
                1 for b in kept_items if b.text not in original_bullets.get(section.name, [])
            )

    change_summary = ChangeSummary(
        reworded_bullets=reworded_total,
        added_sections=[],
        removed_sections=[
            name
            for name, bullets in original_bullets.items()
            if name not in {s.name for s in kept_sections}
        ][:10],
        dropped_bullets=dropped_texts[:50],
        notes=[
            "Every retained bullet is restricted to original CV content; "
            "qualification statements were not expanded.",
        ],
    )
    return ValidationResult(
        content=TailoredContent(
            title=generated.title, sections=[sec.model_copy() for sec in kept_sections]
        ),
        unsupported_claims=unsupported,
        change_summary=change_summary,
    )
