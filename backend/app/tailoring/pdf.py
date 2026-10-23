"""PDF export for approved tailored CVs (WeasyPrint, HTML template).

Only approved drafts are exported: the service layer enforces this and the
`pdf_only_after_approval` DB constraint independently backs it up.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from pathlib import Path

from app.config import get_settings
from app.logging import get_logger
from app.models import TailoredResume
from app.schemas.tailoring import TailoredContent

logger = get_logger(__name__)


def render_html(content: TailoredContent) -> str:
    """Render the approved JSON content as a minimal, print-ready HTML doc."""
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>CV</title><style>",
        "body { font-family: 'DejaVu Sans', sans-serif; font-size: 11pt; margin: 2.2cm; }",
        "h1 { font-size: 16pt; margin: 0 0 4pt 0; }",
        "h2 { font-size: 12pt; border-bottom: 1px solid #444; margin: 14pt 0 6pt 0; }",
        "ul { margin: 0 0 0 14pt; padding: 0; }",
        "li { margin-bottom: 3pt; }",
        ".meta { color: #555; font-size: 9pt; margin-bottom: 8pt; }",
        "</style></head><body>",
    ]
    if content.title:
        parts.append(f"<h1>{escape(content.title)}</h1>")
    parts.append(
        f"<p class='meta'>Approved tailored CV — exported "
        f"{datetime.now(UTC).strftime('%Y-%m-%d')}</p>"
    )
    for section in content.sections:
        parts.append(f"<h2>{escape(section.name.title())}</h2><ul>")
        for bullet in section.items:
            parts.append(f"<li>{escape(bullet.text)}</li>")
        parts.append("</ul>")
    parts.append("</body></html>")
    return "".join(parts)


def export_pdf(tailored: TailoredResume, content: TailoredContent) -> str:
    """Render and store the PDF; returns the stored path.

    Raises ValueError when invoked for a draft that is not approved or has
    no content. The caller must persist `final_pdf_path`.
    """
    if tailored.approval_status != "approved":
        raise ValueError("only approved tailored resumes can be exported to PDF")

    settings = get_settings()
    export_dir = Path(settings.tailored_pdf_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        f"tailored-{str(tailored.resume_id)[:8]}-{str(tailored.job_id)[:8]}-"
        f"v{tailored.version}-{str(tailored.id)[:8]}.pdf"
    )
    output_path = export_dir / filename
    if output_path.resolve().parent != export_dir.resolve():
        raise ValueError("invalid export path")

    html = render_html(content)
    from weasyprint import HTML

    HTML(string=html).write_pdf(str(output_path))
    logger.info("tailored.pdf_exported", tailored_id=tailored.id, path=str(output_path))
    return str(output_path)
