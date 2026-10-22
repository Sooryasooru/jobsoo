"""Deterministic CV parsing into a structured ParsedCV.

Parsers must never invent information: unknown optional fields stay empty.
Section heuristics are intentionally conservative; ambiguous lines are kept
in the section body rather than force-classified.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": (
        "experience",
        "work experience",
        "professional experience",
        "employment",
        "employment history",
    ),
    "education": ("education", "academic background", "academic history"),
    "skills": ("skills", "technical skills", "key skills", "core skills", "competencies"),
    "projects": ("projects", "personal projects", "selected projects", "academic projects"),
    "certifications": ("certifications", "certificates", "licenses"),
}

_EXPERIENCE_LINE = re.compile(
    r"^(?P<title>[^\|()]{3,80}?)\s*[\|\-–—]\s*(?P<company>[^\|()]{2,80}?)"
    r"(?:\s*[\|\-–—]\s*(?P<dates>.+?))?$"
)


class ExperienceEntry(BaseModel):
    """One parsed professional experience item (dates optional)."""

    title: str
    company: str | None = None
    start: str | None = None
    end: str | None = None
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    degree: str
    institution: str | None = None
    year: str | None = None


class ParsedCV(BaseModel):
    """Structured, text-derived CV content. No LLM involved at this layer."""

    full_text: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    experiences: list[ExperienceEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    parse_notes: list[str] = Field(default_factory=list)


def parse_cv_text(text: str) -> ParsedCV:
    """Structure raw CV text using section-header heuristics."""
    cleaned = text.replace("\r\n", "\n").replace("\u00a0", " ")
    lines = [line.strip() for line in cleaned.split("\n") if line.strip()]

    result = ParsedCV(full_text=cleaned[:20000])
    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", cleaned)
    if email_match:
        result.contact_email = email_match.group(0).lower()
    phone_match = re.search(r"(\+?\d[\d\s().-]{7,15}\d)", cleaned)
    if phone_match:
        result.contact_phone = re.sub(r"\s+", " ", phone_match.group(1))

    # Classify lines into sections based on recognized headers.
    sections: dict[str, list[str]] = {}
    current = "header"
    for line in lines:
        matched_section = _match_section_header(line)
        if matched_section is not None:
            current = matched_section
            continue
        sections.setdefault(current, []).append(line)

    result.skills = _split_item_lines(sections.get("skills", []))
    result.projects = _split_item_lines(sections.get("projects", []))
    result.certifications = _split_item_lines(sections.get("certifications", []))
    result.experiences = _parse_experiences(sections.get("experience", []))
    result.education = _parse_education(sections.get("education", []))

    if not sections.get("experience"):
        result.parse_notes.append("No explicit work-experience section detected.")
    if not sections.get("skills"):
        result.parse_notes.append("No explicit skills section detected.")
    return result


def parse_resume_file(path: Path, file_type: str) -> tuple[str, list[str]]:
    """Extract raw text and notes from a stored CV file.

    Raises ValueError for unsupported/undecodable content so callers can
    reject the upload explicitly.
    """
    notes: list[str] = []
    try:
        if file_type in ("txt", "md"):
            return path.read_text(encoding="utf-8", errors="strict"), notes
        if file_type == "docx":
            return parse_docx(path), notes
        if file_type == "pdf":
            return parse_pdf(path, notes), notes
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"could not decode {file_type} content: {exc}") from exc
    raise ValueError(f"unsupported CV file type: {file_type}")


def parse_docx(path: Path) -> str:
    """Extract text from a .docx file."""
    from docx import Document

    document = Document(str(path))
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())


def parse_pdf(path: Path, notes: list[str]) -> str:
    """Extract text from a PDF with pdfminer.six."""
    from pdfminer.high_level import extract_text
    from pdfminer.pdfparser import PDFSyntaxError

    try:
        text = extract_text(str(path))
    except PDFSyntaxError as exc:
        raise ValueError(f"not a readable PDF: {exc}") from exc
    if not text.strip():
        notes.append("PDF produced no extractable text (likely scanned images).")
        return ""
    return text


def _match_section_header(line: str) -> str | None:
    lowered = line.lower().strip().rstrip(":").strip()
    if lowered.isupper() or lowered.endswith(":") or len(lowered.split()) <= 4:
        for section, aliases in SECTION_ALIASES.items():
            if lowered in aliases:
                return section
            if len(lowered) <= 40 and any(phrase in lowered for phrase in aliases):
                return section
    return None


def _split_item_lines(lines: list[str]) -> list[str]:
    """Extract items from section lines, splitting comma-separated runs."""
    items: list[str] = []
    for line in lines:
        candidate = re.sub(r"^[-•*·]+\s*", "", line.strip())
        for part in re.split(r"[;,]\s*", candidate):
            item = part.strip(" •*·-")
            if item and 1 <= len(item) <= 120:
                items.append(item)
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _parse_experience_bullets(lines_with_index: list[tuple[int, str]]) -> list[str]:
    bullets = []
    for _, line in lines_with_index:
        if re.match(r"^[-•*·]", line) or (line.startswith("  ") and len(line) > 5):
            bullets.append(re.sub(r"^[-•*·]+\s*", "", line.strip()))
    return bullets


def _parse_experiences(lines: list[str]) -> list[ExperienceEntry]:
    """Headline lines like `Backend Dev - ACME Ltd - 2021-01 to 2024-02`."""
    entries: list[ExperienceEntry] = []
    current: ExperienceEntry | None = None

    for line in lines:
        is_bullet = bool(re.match(r"^[-•*·]", line)) or (line.startswith("  ") and len(line) > 5)
        if not is_bullet:
            match = _EXPERIENCE_LINE.match(line)
            if match:
                current = ExperienceEntry(
                    title=match.group("title").strip(),
                    company=match.group("company").strip(),
                )
                _attach_dates(current, match.group("dates"))
                entries.append(current)
                continue
        if current is not None and is_bullet:
            bullet_text = re.sub(r"^[-•*·]+\s*", "", line.strip())
            if bullet_text:
                current.bullets.append(bullet_text)
    return entries


def _attach_dates(entry: ExperienceEntry, dates_blob: str | None) -> None:
    if not dates_blob:
        return
    parts = re.split(r"(?:\s*(?:to|through|until|–|—|az)-{0,2}\s*)", dates_blob.strip())
    if len(parts) >= 2:
        entry.start = parts[0].strip() or None
        entry.end = parts[-1].strip() or None
    elif parts:
        entry.start = parts[0].strip() or None


def _parse_education(lines: list[str]) -> list[EducationEntry]:
    entries: list[EducationEntry] = []
    for line in lines:
        degree, _, rest = line.partition(",")
        degree = degree.strip()
        if not degree or len(degree) > 120:
            continue
        institution = rest.split(",")[0].strip() or None if rest else None
        year_match = re.search(r"(19|20)\d{2}", line)
        entries.append(
            EducationEntry(
                degree=degree,
                institution=institution,
                year=year_match.group(0) if year_match else None,
            )
        )
    return entries


def parsed_cv_to_dict(parsed: ParsedCV) -> dict[str, Any]:
    """JSON-serializable form for the resumes.parsed_content JSONB column."""
    return parsed.model_dump(mode="json")
