#!/usr/bin/env python3
"""Check and normalize exam-PDF page geometry locally, without OCR/resampling.

Examples (macOS/Linux, Python 3.10+):
  python normalize_exam_pdfs.py --check Exam3.pdf Rubrics/rubric.pdf
  python normalize_exam_pdfs.py --check --input-dir RawExams --report check.json
  python normalize_exam_pdfs.py --input-dir RawExams --output-dir RawExams_normalized
  python normalize_exam_pdfs.py --input-dir RawExams --output-dir RawExams_normalized --full-scan

The default writes NEW copies, baking /Rotate into contents and page boxes.
--full-scan additionally reveals the entire embedded scan on positively
recognized, single-image pages. Never use this option to undo intentional
cropping/redaction. It cannot recover pixels missing from the embedded image.

Originals and existing destinations are NEVER overwritten. No network calls.
Exit codes: 0 = no detected unresolved issue; 1 = failure; 2 = review needed.
A clean check is not proof that every answer is legible or the API renders it
correctly. The image-extent check is deliberately limited to simple scans.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

try:
    import pypdf
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject, RectangleObject
except ImportError:
    raise SystemExit('Missing pypdf. Install: python -m pip install "pypdf>=5.9,<7"')

VERSION = "2.0.0"
TOLERANCE = 0.01  # PDF points; ignores floating-point noise, not visible margins.
BOX_NAMES = ("/MediaBox", "/CropBox", "/BleedBox", "/TrimBox", "/ArtBox")
IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def close_box(a: list[float], b: list[float]) -> bool:
    return all(abs(x - y) <= TOLERANCE for x, y in zip(a, b))


def rect(value: Any) -> list[float]:
    values = [float(x) for x in value]
    if len(values) != 4 or not all(math.isfinite(x) for x in values):
        raise ValueError("invalid/non-finite page rectangle")
    if values[2] <= values[0] or values[3] <= values[1]:
        raise ValueError("empty or reversed page rectangle")
    return values


def compose(c: tuple[float, ...], m: tuple[float, ...]) -> tuple[float, ...]:
    """Compose PDF affine matrices: old CTM followed by a new 'cm' operation."""
    a, b, cc, d, e, f = c
    aa, bb, c2, dd, ee, ff = m
    return (a * aa + cc * bb, b * aa + d * bb,
            a * c2 + cc * dd, b * c2 + d * dd,
            a * ee + cc * ff + e, b * ee + d * ff + f)


def simple_scan(page: Any) -> dict[str, Any]:
    """Recognize ONLY q/Q/cm/Do content drawing exactly one image XObject.

    Unknown operators, nested forms, inline images, text, multiple images,
    and explicit clipping paths are not guessed at. This is NOT a general
    PDF paint-bounds analyzer. No image decoding or Pillow dependency is used.
    """
    contents = page.get_contents()
    if contents is None:
        return {"recognized": False, "reason": "blank page"}
    matrix = IDENTITY
    stack: list[tuple[float, ...]] = []
    images: list[list[float]] = []
    resources = page.get("/Resources", {})
    if hasattr(resources, "get_object"):
        resources = resources.get_object()
    objects = resources.get("/XObject", {})
    if hasattr(objects, "get_object"):
        objects = objects.get_object()
    for args, op in contents.operations:
        if op == b"q":
            stack.append(matrix)
        elif op == b"Q":
            if not stack:
                return {"recognized": False, "reason": "unbalanced graphics state"}
            matrix = stack.pop()
        elif op == b"cm":
            if len(args) != 6:
                return {"recognized": False, "reason": "invalid affine transform"}
            new = tuple(float(x) for x in args)
            if not all(math.isfinite(x) for x in new):
                return {"recognized": False, "reason": "non-finite affine transform"}
            matrix = compose(matrix, new)
        elif op == b"Do" and len(args) == 1:
            obj = objects.get(args[0])
            if obj is None:
                return {"recognized": False, "reason": "missing image/form resource"}
            obj = obj.get_object()
            if obj.get("/Subtype") != "/Image":
                return {"recognized": False, "reason": "nested form or non-image content"}
            a, b, c, d, e, f = matrix
            corners = [(a * x + c * y + e, b * x + d * y + f)
                       for x, y in ((0, 0), (0, 1), (1, 0), (1, 1))]
            images.append([min(x for x, _ in corners), min(y for _, y in corners),
                           max(x for x, _ in corners), max(y for _, y in corners)])
        else:
            return {"recognized": False,
                    "reason": "not a simple scan; operator " + op.decode("ascii", "replace")}
    if stack or len(images) != 1:
        return {"recognized": False, "reason": "not exactly one balanced image placement"}
    try:
        bounds = rect(images[0])
    except ValueError:
        return {"recognized": False, "reason": "degenerate image placement"}
    return {"recognized": True, "image_bounds_pdf_points": bounds}


def excess(inner: list[float], outer: list[float]) -> dict[str, float]:
    """Excess in unrotated PDF coordinates; bottom-left is the origin."""
    return dict(zip(("left", "bottom", "right", "top"),
                    (max(0.0, outer[0] - inner[0]), max(0.0, outer[1] - inner[1]),
                     max(0.0, inner[2] - outer[2]), max(0.0, inner[3] - outer[3]))))


def image_stream_hashes(page: Any) -> list[str]:
    """Hash encoded image payloads, including nested forms and image masks.

    _data is pypdf's encoded-stream storage, isolated here for verification.
    Refuse rather than silently weaken verification if that representation
    changes in a future library version.
    """
    seen: set[int] = set()
    hashes: list[str] = []

    def walk(value: Any) -> None:
        if value is None:
            return
        obj = value.get_object() if hasattr(value, "get_object") else value
        if not hasattr(obj, "get") or id(obj) in seen:
            return
        seen.add(id(obj))
        if obj.get("/Subtype") == "/Image":
            raw = getattr(obj, "_data", None)
            if not isinstance(raw, bytes):
                raise ValueError("cannot verify encoded image stream with this pypdf version")
            hashes.append(digest(raw))
            for name in ("/SMask", "/Mask"):
                mask = obj.get(name)
                if mask is not None and not isinstance(mask, list):
                    walk(mask)
        resources = obj.get("/Resources")
        if resources is not None:
            resources = resources.get_object()
            objects = resources.get("/XObject")
            if objects is not None:
                for child in objects.get_object().values():
                    walk(child)

    walk(page)
    return sorted(hashes)


def audit_reader(reader: PdfReader) -> dict[str, Any]:
    if reader.is_encrypted:
        raise ValueError("encrypted PDF: not supported by this utility")
    if not reader.pages:
        raise ValueError("PDF has no pages")
    root = reader.trailer["/Root"]
    blockers = []
    if root.get("/AcroForm"):
        blockers.append("interactive form/signature fields")
    if root.get("/Perms"):
        blockers.append("document permissions/signatures")
    records = []
    for number, page in enumerate(reader.pages, 1):
        media, crop = rect(page.mediabox), rect(page.cropbox)
        raw_rotation = float(page.get("/Rotate", 0))
        if not math.isfinite(raw_rotation) or raw_rotation % 90 != 0:
            raise ValueError(f"page {number}: rotation is not an integer multiple of 90 degrees")
        rotation = int(raw_rotation) % 360
        unit = float(page.get("/UserUnit", 1))
        if not math.isfinite(unit) or unit <= 0:
            raise ValueError(f"page {number}: invalid UserUnit")
        issues = []
        if raw_rotation != 0:
            issues.append("rotation_metadata")
        if abs(media[0]) > TOLERANCE or abs(media[1]) > TOLERANCE:
            issues.append("nonzero_page_origin")
        if not close_box(crop, media):
            issues.append("cropbox_differs_from_mediabox")
        if unit != 1.0:
            issues.append("nonstandard_user_unit")
            blockers.append(f"page {number}: UserUnit={unit}; normalize separately")
        annots = page.get("/Annots")
        if annots is not None and len(annots.get_object()) > 0:
            issues.append("annotations_present")
            blockers.append(f"page {number}: annotations")
        auxiliary = {}
        for key in BOX_NAMES[2:]:
            if key in page:
                auxiliary[key] = rect(page[key])
                if not close_box(auxiliary[key], media):
                    issues.append(key[1:].lower() + "_differs_from_mediabox")
        scan = simple_scan(page)
        if scan["recognized"]:
            bounds = scan["image_bounds_pdf_points"]
            scan["outside_media_points"] = excess(bounds, media)
            scan["outside_crop_points"] = excess(bounds, crop)
            if max(scan["outside_media_points"].values()) > TOLERANCE:
                issues.append("scan_extends_outside_mediabox")
            if max(scan["outside_crop_points"].values()) > TOLERANCE:
                issues.append("scan_extends_outside_cropbox")
        width, height = (media[2] - media[0]) * unit, (media[3] - media[1]) * unit
        if rotation in (90, 270):
            width, height = height, width
        records.append({"page": number, "rotation_degrees": rotation,
                        "stored_rotation_degrees": raw_rotation,
                        "media_box_pdf_points": media, "crop_box_pdf_points": crop,
                        "auxiliary_boxes_pdf_points": auxiliary, "user_unit": unit,
                        "displayed_media_size_points": [width, height],
                        "simple_scan": scan, "issues": issues})
    return {"page_count": len(records), "normalization_blockers": blockers,
            "pages_needing_attention": [x["page"] for x in records if x["issues"]],
            "simple_scan_pages_checked": sum(x["simple_scan"]["recognized"] for x in records),
            "pages": records}


def normalize_data(data: bytes, *, full_scan: bool = False) -> tuple[bytes, dict[str, Any]]:
    reader = PdfReader(io.BytesIO(data))
    before = audit_reader(reader)
    if before["normalization_blockers"]:
        raise ValueError("normalization refused: " + "; ".join(before["normalization_blockers"]))
    original_images = [image_stream_hashes(p) for p in reader.pages]
    writer = PdfWriter(clone_from=reader)
    changes = []
    expected_sizes = []
    for page, record in zip(writer.pages, before["pages"]):
        actions = []
        media = record["media_box_pdf_points"]
        scan = record["simple_scan"]
        if full_scan and scan["recognized"]:
            image = scan["image_bounds_pdf_points"]
            target = [min(media[0], image[0]), min(media[1], image[1]),
                      max(media[2], image[2]), max(media[3], image[3])]
            existing = [media, record["crop_box_pdf_points"]]
            existing.extend(record["auxiliary_boxes_pdf_points"].values())
            if any(not close_box(box, target) for box in existing):
                for key in BOX_NAMES:
                    page[NameObject(key)] = RectangleObject(target)
                actions.append("page_boxes_expanded_to_full_scan")
                media = target
        elif full_scan and any("box_differs" in item for item in record["issues"]):
            raise ValueError(f"page {record['page']}: --full-scan cannot remove cropping "
                             "from a page not recognized as a simple single-image scan")
        width, height = media[2] - media[0], media[3] - media[1]
        if record["rotation_degrees"] in (90, 270):
            width, height = height, width
        expected_sizes.append([width, height])
        if record["stored_rotation_degrees"] != 0 or abs(media[0]) > TOLERANCE or abs(media[1]) > TOLERANCE:
            # Transform both the content and ALL existing page boxes, not just
            # /Rotate. Calling this with zero rotation also normalizes the origin.
            page.transfer_rotation_to_content()
            actions.append("rotation_and_origin_baked_into_content")
        if actions:
            changes.append({"page": record["page"], "actions": actions})
    if changes:
        buffer = io.BytesIO()
        writer.write(buffer)
        output = buffer.getvalue()
    else:
        # Preserve every byte of PDFs that need no transformation.
        output = data
    check_reader = PdfReader(io.BytesIO(output))
    after = audit_reader(check_reader)
    if after["page_count"] != before["page_count"]:
        raise ValueError("verification failed: page count changed")
    for original, result, expected, page in zip(original_images, after["pages"], expected_sizes, check_reader.pages):
        if result["stored_rotation_degrees"] != 0:
            raise ValueError("verification failed: output still has rotation metadata")
        if not all(abs(a - b) <= TOLERANCE for a, b in zip(result["displayed_media_size_points"], expected)):
            raise ValueError("verification failed: unexpected displayed page dimensions")
        if original != image_stream_hashes(page):
            raise ValueError("verification failed: encoded image payloads changed")
        if full_scan and result["simple_scan"]["recognized"]:
            outside = result["simple_scan"]["outside_crop_points"]
            if max(outside.values()) > TOLERANCE:
                raise ValueError("verification failed: scan remains outside the page view")
    return output, {"before": before, "after": after, "changes": changes,
                    "encoded_image_streams_unchanged": True,
                    "byte_identical_copy": output == data,
                    "output_sha256": digest(output)}


def write_new_atomic(destination: Path, data: bytes) -> None:
    """Publish a complete new file without overwriting (local macOS/Linux)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)  # Atomic no-clobber; local filesystem.
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", nargs="*", type=Path, help="Explicit PDFs; otherwise read --input-dir.")
    parser.add_argument("--input-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("./RawExams_normalized"))
    parser.add_argument("--check", action="store_true", help="Read-only audit; no PDF copies.")
    parser.add_argument("--full-scan", action="store_true", help="Explicitly reveal full recognized scans in output copies.")
    parser.add_argument("--report", type=Path, help="Write a NEW JSON report (also allowed with --check).")
    args = parser.parse_args(argv)
    if args.pdfs and args.input_dir is not None:
        parser.error("Use explicit PDF paths OR --input-dir, not both")
    if args.check and args.full_scan:
        parser.error("--full-scan changes PDFs; omit it during a read-only --check")
    if args.pdfs:
        paths = args.pdfs
    else:
        directory = args.input_dir or Path("./RawExams")
        if not directory.is_dir():
            parser.error(f"Input directory does not exist: {directory}")
        paths = sorted((p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
                       key=lambda p: p.name.casefold())
    if not paths or any(not p.is_file() or p.suffix.lower() != ".pdf" for p in paths):
        parser.error("Provide at least one existing PDF file")
    if len({p.resolve() for p in paths}) != len(paths):
        parser.error("The same input PDF was supplied more than once")
    destinations = [args.output_dir / p.name for p in paths] if not args.check else []
    if len({p.name.casefold() for p in destinations}) != len(destinations):
        parser.error("Duplicate destination filenames; use separate output directories")
    source_paths = {p.resolve() for p in paths}
    for destination in destinations + ([args.report] if args.report else []):
        if destination.resolve() in source_paths or os.path.lexists(destination):
            parser.error(f"Refusing to overwrite: {destination}; choose a new output/report path")
    if args.report and args.report.resolve() in {p.resolve() for p in destinations}:
        parser.error("Report must not have the same path as an output PDF")
    report: dict[str, Any] = {
        "tool": Path(__file__).name, "version": VERSION, "pypdf_version": pypdf.__version__,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "check" if args.check else "normalize", "full_scan": args.full_scan,
        "scope": "page geometry and simple single-image scan extents; not OCR/legibility/API validation",
        "files": [],
    }
    failures = review = 0
    for path in paths:
        record: dict[str, Any] = {"source": str(path), "filename": path.name}
        try:
            data = path.read_bytes()
            record.update({"source_sha256": digest(data), "source_bytes": len(data)})
            if args.check:
                audit = audit_reader(PdfReader(io.BytesIO(data)))
                record["before"] = audit
            else:
                output, result = normalize_data(data, full_scan=args.full_scan)
                record.update(result)
                destination = args.output_dir / path.name
                write_new_atomic(destination, output)
                record["output"] = str(destination)
                audit = result["after"]
            unresolved = bool(audit["pages_needing_attention"] or audit["normalization_blockers"])
            record["status"] = "review_needed" if unresolved else "ok"
            review += int(unresolved)
            counts = Counter(issue for page in audit["pages"] for issue in page["issues"])
            details = "; ".join(f"{item}: {n} page(s)" for item, n in sorted(counts.items()))
            action = "checked" if args.check else f"wrote {record['output']}"
            print(f"{path.name}: {audit['page_count']} pages; {action}; {record['status']}")
            if details:
                print("  " + details)
            if not args.check:
                print(f"  {len(record['changes'])} page(s) changed; encoded image streams verified unchanged")
            if audit["simple_scan_pages_checked"] != audit["page_count"]:
                print(f"  Full image-extent check available for {audit['simple_scan_pages_checked']} "
                      f"of {audit['page_count']} simple scan pages (not a general content check)")
        except Exception as exc:
            failures += 1
            record.update({"status": "failed", "error": str(exc)})
            print(f"ERROR {path.name}: {exc}", file=sys.stderr)
        report["files"].append(record)
    report["summary"] = {"files": len(paths), "failed": failures, "review_needed": review}
    if args.report:
        write_new_atomic(args.report, (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("ascii"))
        print(f"Report: {args.report}")
    print("Originals unchanged. Inspect representative pages and test a small scoring batch.")
    return 1 if failures else (2 if review else 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
