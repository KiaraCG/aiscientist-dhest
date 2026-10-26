#!/usr/bin/env python3
"""Run the local synthetic example without reading credentials or making AI calls.

Creates a fresh demo workspace, checks the unscored inputs, then copies MANUALLY
AUTHORED SYNTHETIC grade fixtures into evals and demonstrates compilation.
This exercises file plumbing; it does not measure model scoring accuracy.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("demo_workspace"))
    args = parser.parse_args(argv)
    target = args.output_dir.resolve()
    if target.exists():
        parser.error("Demo destination already exists; choose a fresh --output-dir")
    root = Path(__file__).resolve().parent
    shutil.copytree(root / "examples/minimal_exam", target)
    config = target / "exam_config.json"
    def run(script, *extra):
        subprocess.run([sys.executable, str(root / script), "--config", str(config), *extra], check=True)
    run("prepare_exam.py")
    run("score_exams.py", "--check")
    shutil.copytree(target / "synthetic_evals", target / "evals")
    run("compile_ai_grades.py", "--require-complete")
    print("\nSYNTHETIC DEMO ONLY: no model was called; evals contains authored fixtures, not AI scores.")
    print(f"Workbooks are in {target}. These fixtures have no model provenance sidecars.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
