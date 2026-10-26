#!/usr/bin/env python3
"""Build toolkit workspaces from baseline JSON exam + solution files.

Requires reportlab (see requirements-dev.txt) to author Rubrics/rubric.pdf.
Does not call any model API.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT.parent / "aiscientist-dhest-basic-baseline"
TEMPLATE_PROMPT = ROOT / "examples/minimal_exam/Prompts/prompt.template.txt"
SCHEMAS = ROOT / "formats/json_exam"

EXAM_SPECS = [
    ("signals-and-systems", "hs17"),
    ("signals-and-systems", "hs18"),
    ("signals-and-systems", "hs19"),
    ("signals-and-systems", "hs20"),
    ("signals-and-systems", "hs21"),
    ("biological-methods-for-engineers", "hs25_mock_theory"),
    ("biological-methods-for-engineers", "hs25_mock_protocols"),
]


def slug(course: str, exam_id: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", f"{course}_{exam_id}".lower()).strip("_")


def short_name(qid: str, text: str, limit: int = 72) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line or qid
    return one_line[: limit - 3].rstrip() + "..."


def option_index(options: list[str], correct: str) -> tuple[str, str]:
    for i, opt in enumerate(options, start=1):
        if opt == correct:
            return str(i), opt
    for i, opt in enumerate(options, start=1):
        if opt.strip() == correct.strip():
            return str(i), opt
    return "1", correct[:200]


def manifest_item(q: dict, key: dict) -> dict:
    qid = q["id"]
    maximum = key.get("points", q.get("points", 1))
    name = short_name(qid, q.get("text", qid))
    part = qid
    problem = re.sub(r"^q", "", qid) or "1"
    qtype = key.get("type", q.get("type"))
    base = {
        "rubric_item": qid,
        "rubric_name": name,
        "max_points": maximum,
        "part_id": part,
        "problem_id": problem,
        "notes": "",
        "dependencies": [],
    }
    if qtype == "single-choice":
        opts = q.get("options") or []
        opt_num, opt_text = option_index(opts, str(key.get("correctAnswer", "")))
        return {
            **base,
            "score_mode": "allowed",
            "allowed_points": [0, maximum],
            "correct_option": opt_num,
            "correct_answer": opt_text,
        }
    if qtype == "multiple-choice":
        return {
            **base,
            "score_mode": "allowed",
            "allowed_points": [0, maximum],
            "notes": "Award full credit only for the complete correct set of options.",
        }
    if qtype == "number":
        tol = key.get("tolerance", 0)
        return {
            **base,
            "score_mode": "continuous",
            "notes": f"Reference value: {key.get('correctAnswer')!r}; tolerance ±{tol}.",
        }
    sample = key.get("sampleAnswer", "")
    notes = ""
    if sample:
        notes = "Use the rubric PDF reference answer; award partial credit for identifiable correct content."
    return {**base, "score_mode": "continuous", "notes": notes}


def rubric_rule(q: dict, key: dict) -> str:
    qtype = key.get("type", q.get("type"))
    if qtype == "single-choice":
        opts = q.get("options") or []
        opt_num, opt_text = option_index(opts, str(key.get("correctAnswer", "")))
        lines = [f"Question ({q['id']}): {q.get('text', '')}"]
        if opts:
            lines.append("Options:")
            for i, o in enumerate(opts, start=1):
                lines.append(f"  ({i}) {o}")
        lines.append(
            f"Award full credit only for unambiguous selection of option ({opt_num}): {opt_text}. "
            "Otherwise 0 unless the rubric allows partial credit."
        )
        return "\n".join(lines)
    if qtype == "multiple-choice":
        ans = key.get("correctAnswers") or []
        return (
            f"Question ({q['id']}): {q.get('text', '')}\n"
            f"Correct set: {', '.join(ans) or '(see instructor key)'}. All-or-nothing unless noted."
        )
    if qtype == "number":
        return (
            f"Question ({q['id']}): {q.get('text', '')}\n"
            f"Reference: {key.get('correctAnswer')} (tolerance ±{key.get('tolerance', 0)})."
        )
    sample = key.get("sampleAnswer", "")
    body = f"Question ({q['id']}): {q.get('text', '')}"
    if sample:
        body += f"\nReference answer: {sample}"
    body += "\nAward up to the maximum for demonstrated correct content; use partial credit when appropriate."
    return body


def write_rubric_pdf(path: Path, title: str, items: list[dict], questions: list[dict], keys: dict) -> None:
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="RubricHeading",
            parent=styles["Heading2"],
            fontSize=10,
            leading=13,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#173D4C"),
        )
    )
    styles["Normal"].fontSize = 9
    styles["Normal"].leading = 12
    story: list = []
    story.append(Paragraph(escape(title), styles["Title"]))
    story.append(
        Paragraph(
            escape(
                "Combined question sheet and scoring rubric generated from JSON source. "
                "Criterion headings match rubric_manifest.json."
            ),
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 8))
    q_by_id = {q["id"]: q for q in questions}
    for item in items:
        q = q_by_id[item["rubric_item"]]
        key = keys[item["rubric_item"]]
        pts = item["max_points"]
        pt_word = "point" if pts == 1 else "points"
        heading = f"{item['rubric_item']} - {item['rubric_name']} - {pts} {pt_word}:"
        story.append(Paragraph(escape(heading), styles["RubricHeading"]))
        rule = rubric_rule(q, key).replace("\n", "<br/>")
        story.append(Paragraph(rule, styles["Normal"]))
        if len(story) > 400:
            story.append(PageBreak())

    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.drawString(42, 26, "JSON-derived rubric — verify before live scoring")
        canvas.drawRightString(A4[0] - 42, 26, str(doc.page))

    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=42,
        rightMargin=42,
        topMargin=42,
        bottomMargin=44,
        title=title,
    ).build(story, onFirstPage=footer, onLaterPages=footer)


def build_workspace(course: str, exam_suffix: str, *, overwrite: bool) -> Path:
    if not BASELINE.is_dir():
        raise SystemExit(f"Baseline repo not found at {BASELINE}")
    exam_path = BASELINE / "data" / course / f"exam_{exam_suffix}.json"
    sol_path = BASELINE / "data" / course / f"solution_{exam_suffix}.json"
    if not exam_path.is_file() or not sol_path.is_file():
        raise SystemExit(f"Missing {exam_path} or {sol_path}")

    exam = json.loads(exam_path.read_text(encoding="utf-8"))
    solution = json.loads(sol_path.read_text(encoding="utf-8"))
    questions = exam["questions"]
    items = []
    for q in questions:
        qid = q["id"]
        if qid not in solution:
            raise SystemExit(f"{exam_path}: no solution entry for {qid}")
        items.append(manifest_item(q, solution[qid]))

    total = sum(i["max_points"] for i in items)
    ws_name = slug(course, exam_suffix)
    ws = ROOT / "workspaces" / ws_name
    if ws.exists() and not overwrite:
        raise SystemExit(f"{ws} exists; pass --overwrite to replace generated files")

    for sub in ("Rubrics", "Prompts", "RawExams", "source", "evals"):
        (ws / sub).mkdir(parents=True, exist_ok=True)

    shutil.copy2(exam_path, ws / "source" / exam_path.name)
    shutil.copy2(sol_path, ws / "source" / sol_path.name)
    if SCHEMAS.is_dir():
        for name in ("exam_schema.json", "solution_schema.json", "llm_output_schema.json"):
            src = SCHEMAS / name
            if src.is_file():
                shutil.copy2(src, ws / "source" / name)

    exam_id = re.sub(r"[^A-Za-z0-9._-]+", "_", exam.get("examId", ws_name))
    is_mc = course.startswith("signals")
    notes = (
        "Adapted from JSON baseline exams. Multiple-choice: match option text in the student PDF, "
        "not position alone. No negative marking."
        if is_mc
        else "Adapted from JSON baseline mock exams. Free-text items use reference answers in the rubric PDF; "
        "award partial credit for identifiable correct content."
    )

    config = {
        "schema_version": 1,
        "exam_id": exam_id,
        "exam_title": exam.get("title", ws_name),
        "approved_for_scoring": False,
        "paths": {
            "manifest": "rubric_manifest.json",
            "rubric": "Rubrics/rubric.pdf",
            "prompt_template": "Prompts/prompt.template.txt",
            "prompt": "Prompts/prompt.txt",
            "exams": "RawExams",
            "evals": "evals",
        },
        "filename_pattern": r"^(?P<id>[A-Za-z0-9._-]+)$",
        "identity_mode": "text",
        "max_combined_pdf_bytes": 50000000,
        "rubric_validation": {"mode": "headings", "approved_sha256": ""},
        "notes": notes,
    }
    manifest = {"exam_id": exam_id, "expected_total_max_points": total, "items": items}

    (ws / "exam_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    (ws / "rubric_manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    shutil.copy2(TEMPLATE_PROMPT, ws / "Prompts/prompt.template.txt")
    write_rubric_pdf(ws / "Rubrics/rubric.pdf", exam.get("title", ws_name), items, questions, solution)

    import prepare_exam

    prepare_exam.main(["--config", str(ws / "exam_config.json"), "--overwrite"])

    readme = ws / "RawExams/README.txt"
    readme.write_text(
        "Place one complete student submission PDF per file here.\n"
        "Filename stem must match filename_pattern in exam_config.json (default: any alphanumeric id).\n"
        "The baseline JSON pipeline used structured answers instead of scans; this folder is for the toolkit workflow.\n",
        encoding="utf-8",
    )
    return ws


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--course", help="e.g. signals-and-systems")
    p.add_argument("--exam-id", help="e.g. hs21 (exam_hs21.json suffix)")
    p.add_argument("--all", action="store_true", help="Build all known baseline exams")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    if args.all:
        for course, suffix in EXAM_SPECS:
            ws = build_workspace(course, suffix, overwrite=args.overwrite)
            print(f"Built {ws}")
        return

    if not args.course or not args.exam_id:
        p.error("Specify --course and --exam-id, or use --all")
    ws = build_workspace(args.course, args.exam_id, overwrite=args.overwrite)
    print(f"Built {ws}")


if __name__ == "__main__":
    main()
