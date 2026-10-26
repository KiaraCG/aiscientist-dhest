"""Read-only PDF guard, shared with preparation and scoring. No local OCR."""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
import io
from pathlib import Path
import re
import unicodedata

from exam_common import Config, ExamError, number, sha256
from normalize_exam_pdfs import audit_reader
from pypdf import PdfReader


@dataclass(frozen=True)
class PDFInput:
    path: Path
    data: bytes
    page_count: int
    simple_scan_pages: int
    sha256: str
    text: str = ""


def read_pdf(path: Path, *, extract_text: bool = False, byte_limit: int = 50_000_000) -> PDFInput:
    if path.is_symlink() or not path.is_file():
        raise ExamError(f"Not an ordinary PDF file: {path}")
    size = path.stat().st_size
    if not 0 < size < byte_limit:
        raise ExamError(f"{path}: empty or at/above the configured request byte limit")
    data = path.read_bytes()
    if len(data) != size or b"%PDF-" not in data[:1024]:
        raise ExamError(f"{path}: changed size or missing PDF header")
    try:
        reader = PdfReader(io.BytesIO(data))
        audit = audit_reader(reader)
        issues = []
        if audit["normalization_blockers"]:
            issues.extend(audit["normalization_blockers"])
        for page in audit["pages"]:
            if page["issues"]:
                issues.append(f"PDF p. {page['page']}: {', '.join(page['issues'])}")
        if issues:
            raise ExamError(f"{path}: PDF geometry needs inspection before upload:\n  - " +
                            "\n  - ".join(issues) + "\nUse normalize_exam_pdfs.py separately; never suppress genuine missing work.")
        txt = "\n".join(p.extract_text() or "" for p in reader.pages) if extract_text else ""
        return PDFInput(path, data, len(reader.pages), audit["simple_scan_pages_checked"], sha256(data), txt)
    except ExamError:
        raise
    except Exception as exc:
        raise ExamError(f"Cannot inspect {path}: {type(exc).__name__}: {exc}") from exc


def validate_rubric(config: Config) -> PDFInput:
    mode = config.raw["rubric_validation"]["mode"]
    pdf = read_pdf(config.file("rubric"), extract_text=mode == "headings",
                   byte_limit=config.raw["max_combined_pdf_bytes"])
    if mode == "sha256":
        if pdf.sha256 != config.raw["rubric_validation"]["approved_sha256"]:
            raise ExamError("Rubric PDF differs from the manually approved SHA256")
        return pdf
    # A heading is a complete line. See docs/FORMATS.md. Scanned/image-only or
    # complex layout PDFs use explicit manually approved hash mode, not guessed OCR.
    pattern = re.compile(r"(?m)^\s*([A-Za-z0-9][A-Za-z0-9_.()-]*)\s+-\s+([^\r\n]+?)\s+-\s+([0-9]+(?:\.[0-9]+)?)\s*(?:points?|Punkte?)?\s*:?\s*$")
    found = pattern.findall(pdf.text)
    if len(found) != len(config.items):
        raise ExamError(f"Rubric contains {len(found)} recognized criterion headings; expected {len(config.items)}. "
                        "Use the approved combined rubric, or documented sha256 validation for non-extractable headings.")
    def comparable(s):
        return "".join(unicodedata.normalize("NFKC", s).split())
    for (label, name, maximum), item in zip(found, config.items):
        if label != item.label or comparable(name) != comparable(item.name) or number(Decimal(maximum), label) != item.maximum:
            raise ExamError(f"Rubric heading {label} differs from manifest criterion {item.label}")
    return pdf


def check_pair(exam: PDFInput, rubric: PDFInput, config: Config) -> None:
    if len(exam.data) + len(rubric.data) >= config.raw["max_combined_pdf_bytes"]:
        raise ExamError(f"Rubric plus {exam.path.name} reaches the configured combined PDF byte limit")
