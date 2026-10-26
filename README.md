# Exam scoring toolkit

**A configurable starting point for adapting the whole-PDF exam-scoring workflow to a new exam.** This is source code and an operating guide, not an autonomous assessment service. Instructors supply and approve the questions, rubric, reference answers, point rules, and final decisions.

Version 1.0.0 | Prepared 2 October 2026

The exam-specific information lives in JSON and a prompt template, not in duplicated Python item lists. The familiar layout remains `Rubrics/rubric.pdf`, `Prompts/prompt.txt`, `RawExams/`, and `evals/`. The code reads one complete approved rubric and one complete student submission per model request. It does not locally OCR, transcribe, crop, split or resample those files.

**This package contains a placeholder-only `.env.example`. It does not contain `.env`, real student work, real scoring results, or the source exams/answer keys.** The three example PDFs and two example result JSON files are newly authored synthetic fixtures, explicitly labeled as such.

## Start here: an offline demonstration

Run from the unpacked toolkit directory on macOS or Linux. Use Python 3.10 or newer; select your installed interpreter explicitly when `python3` points to an older version.

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check

python -m unittest discover -s tests -v
python run_demo.py
```

The demo creates a **new** `demo_workspace` and refuses to overwrite an existing one. It checks the synthetic rubric and PDFs, then compiles the two authored example results into:

```text
demo_workspace/ai_grades.xlsx
demo_workspace/human_reviews.xlsx
demo_workspace/ai_grades.csv
demo_workspace/human_reviews.csv
```

No credentials are read and no model is called by the demo or tests. Installing packages does require access to your package repository. A second demo can use `python run_demo.py --output-dir demo_workspace_2`. The example's five criteria total six points; its two authored scores total six and four. These are software fixtures, not model-performance measurements.

## Which file does what?

| Source | Responsibility |
|---|---|
| `exam_common.py` | Load and validate the configuration and ordered rubric manifest; validate result JSON; generate the common response schema; preserve identities and point rules. |
| `prepare_exam.py` | Check the supplied rubric and build the exact scoring prompt from the template, notes, and manifest. No AI-based rubric or answer-key generation. |
| `normalize_exam_pdfs.py` | Inspect and, when explicitly requested, normalize scan geometry into separate copies. Never overwrite originals. |
| `pdf_inputs.py` | Read-only PDF guard used by preparation and scoring; distinguish page geometry from scan legibility. |
| `score_exams.py` | Upload rubric then student PDF; request structured scores; validate; save results and provenance; clean up uploaded files on a best-effort basis. |
| `compile_ai_grades.py` | Produce the historical score matrix and a separate human-review workbook/CSV, with summaries, explanations, and source hashes. No AI requests. |
| `run_demo.py` | Demonstrate the local pipeline using only the invented example. |
| `make_shareable_zip.py` | Build a new source archive from an explicit allowlist, not by recursively zipping an exam workspace. |
| `tools/build_demo_materials.py` | Regenerate the synthetic PDF/JSON fixtures. Optional development dependency: ReportLab. |

Keep these Python modules together. Each command can use a different exam workspace through `--config /path/to/exam_config.json`. Configured file paths resolve relative to that configuration file. An explicit command-line `--output-dir` resolves relative to the shell's current directory.

## Adapt a real exam

Read [ADAPT_AN_EXAM.md](docs/ADAPT_AN_EXAM.md) before changing the example. The minimum human-authored materials are a combined rubric PDF, an ordered `rubric_manifest.json`, `exam_config.json`, and `Prompts/prompt.template.txt`. Put complete, identified, preflighted submissions in that exam's `RawExams`. Create a local `.env` from `.env.example` only in the private exam workspace.

The normal sequence is:

```bash
python prepare_exam.py --config workspaces/my_exam/exam_config.json
python score_exams.py --config workspaces/my_exam/exam_config.json --check

# Only after the instructor's approval, local configuration, and pilot planning:
python score_exams.py --config workspaces/my_exam/exam_config.json --exam Exam001.pdf
python score_exams.py --config workspaces/my_exam/exam_config.json
python compile_ai_grades.py --config workspaces/my_exam/exam_config.json --require-complete
```

The example starts with `approved_for_scoring=false`. Real uploads are blocked until the local configuration is explicitly approved. This is an operator guard, not an institutional approval system.

## What is deliberately unchanged, and what is new?

The whole-exam/two-PDF workflow, five fields per criterion, exam-level review flag, local PDF normalization, filename-stem preservation, and score/review exports follow the supplied specialist scripts. The separation of exam data from Python is new. So are the configurable point modes, explicit approval guard, and **provenance-aware resume**. The direct OpenAI adapter is an optional addition; the established Azure adapter remains the default. See [ARCHITECTURE_AND_CHANGES.md](docs/ARCHITECTURE_AND_CHANGES.md).

An older specialist scorer skipped any complete, valid JSON. This generic scorer skips it only when a separate `.provenance` record also matches the current inputs, code, installed library versions and live request settings. A mismatch or missing sidecar stops the run and asks for a fresh output directory. It does not overwrite or silently adopt old scores. The ordinary grade JSON format remains unchanged.

## Guides

- [Adapt an exam](docs/ADAPT_AN_EXAM.md): from separate question/rubric files to an approved, validated pilot.
- [Formats and scoring rules](docs/FORMATS.md): identifiers, point modes, dependencies, JSON contract, exports.
- [Operations](docs/OPERATIONS.md): environment, API boundaries, costs, restarts, locks, provenance, and failures.
- [Situations encountered](docs/KNOWN_SITUATIONS.md): cropping, missing keys, variants, extra pages, fallback results, conflicting solutions, and custom-job traps.
- [Human review](docs/HUMAN_REVIEW.md): triage versus independent rescoring, flagged/unflagged cases, and limitations.
- [Security and sharing](docs/SECURITY_AND_SHARING.md): what is and is not in a shareable archive.
- [Architecture and changes](docs/ARCHITECTURE_AND_CHANGES.md): code boundaries, new design choices, and unsupported extensions.
- [Sources and references](docs/REFERENCES.md): earlier workflow sources versus newly added mechanisms and vendor documentation.

## Scope and validation

The included tests exercise local code and simulated provider responses; the synthetic PDFs demonstrate file flow, not handwriting recognition. **No live Azure or OpenAI inference was performed for this generic release.** A passing local check does not establish deployment availability, model quality, correct student identification, rubric validity, or an appropriate institutional process.

The implementation targets a normal local macOS/Linux filesystem. Native Windows is not supported by its `fcntl` locks; use a suitable Linux environment or adapt and retest locking. Do not assume locks are reliable across network filesystems or synchronized cloud folders. Dependencies are compatibility ranges, not a reproducible environment lock. After a successful local and model-side pilot, retain a private `pip freeze` snapshot alongside the experiment record.

Do not replace a working specialist exam project merely to read this package. Start in a separate workspace and validate an adaptation before using its scores. See `NOTICE.md` for source and licensing limitations and `VALIDATION.md` for the checks actually performed.
