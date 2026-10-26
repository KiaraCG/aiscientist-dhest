#!/usr/bin/env python3
"""Generate Prompts/prompt.txt from reviewed manifest, template and exam notes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import uuid
from exam_common import ExamError, generated_prompt, load_config, write_new
from pdf_inputs import validate_rubric


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("exam_config.json"))
    p.add_argument("--check", action="store_true", help="Validate only; no files written")
    p.add_argument("--overwrite", action="store_true", help="Back up an existing prompt before replacing it")
    args = p.parse_args(argv)
    config = load_config(args.config)
    rubric = validate_rubric(config)
    content = generated_prompt(config).encode("utf-8")
    target = config.file("prompt")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise ExamError(f"Not an ordinary prompt path: {target}")
    same = target.exists() and target.read_bytes() == content
    if args.check:
        if not same:
            raise ExamError("Generated prompt is missing or stale; run prepare_exam.py (use --overwrite to replace)")
        print("Config, rubric headings/hash and generated prompt agree. No files written.")
    elif same:
        print(f"Prompt is already current: {target}")
    else:
        if target.exists():
            if not args.overwrite:
                raise ExamError("Prompt exists; use --overwrite or a fresh project")
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
            backup = target.parent / ".prompt_backups" / (stamp + ".txt")
            write_new(backup, target.read_bytes())
            # Publication remains atomic; this command must not run during scoring.
            temporary = target.with_name("." + target.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                write_new(temporary, content)
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
            print(f"Previous prompt backed up: {backup}")
        else:
            write_new(target, content)
        print(f"Wrote {target}")
    print(f"{config.raw['exam_id']}: {len(config.items)} criteria, {config.total} points; rubric {rubric.page_count} pages")
    if not config.raw["approved_for_scoring"]:
        print("Not approved for live scoring. Human review is required before changing approved_for_scoring to true.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExamError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
