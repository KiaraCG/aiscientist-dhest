# Adapting an exam

This guide separates decisions the instructor must make from mechanical checks the software can perform. A syntactically valid manifest is not an approved rubric.

## 1. Establish scope and authority

Identify the exact exam version, which question parts are to be AI-scored, and which are handled elsewhere. Obtain the question statements, diagrams, rubric, reference solutions and the authoritative multiple-choice key. Keep a written record of their versions and instructor approval. A student's completed paper is evidence to be scored, **not an answer key**.

When questions and rubric arrive separately, make a combined, human-readable rubric PDF containing the necessary question text and figures near the relevant criteria. Include shared data, permitted fallback expressions, units and constants where needed. Retain instructor wording and point allocations unless the instructor explicitly approves a change. Do not silently resolve a wrong sign, inconsistent benchmark or ambiguous criterion by substituting a preferred answer.

There is deliberately no universal program that manufactures a scoring rubric from arbitrary PDFs. Layout and mathematical meaning require review. Prepare the PDF in your normal authoring tool. The included `tools/build_demo_materials.py` is only a generator for the invented demonstration, not a general rubric converter.

## 2. Create a clean private workspace

From the toolkit root:

```bash
mkdir -p workspaces/my_exam/Rubrics workspaces/my_exam/Prompts workspaces/my_exam/RawExams
cp examples/minimal_exam/exam_config.json workspaces/my_exam/exam_config.json
cp examples/minimal_exam/rubric_manifest.json workspaces/my_exam/rubric_manifest.json
cp examples/minimal_exam/Prompts/prompt.template.txt workspaces/my_exam/Prompts/prompt.template.txt
cp .env.example workspaces/my_exam/.env
```

These commands copy configuration templates, not the synthetic submissions or results. Replace the invented exam title, identifier, notes and **all** manifest criteria. Supply your own `Rubrics/rubric.pdf`. Keep `approved_for_scoring=false` during preparation. Your `.env` is private and is never needed for preparation, normalization, compilation or the offline tests.

The Python files stay together in the toolkit root. There is no requirement to copy or modify a separate scorer for every course. Commands select the workspace with `--config`.

## 3. Define the scoreable items, not just problem totals

Use one manifest entry for each independently scored criterion. Preserve stable IDs and exact display names. For example, `2.c.b` can identify the second criterion in question part `2(c)`; it does not mean that the student has a question part `(b)` on that page. Specify `part_id` and `problem_id` explicitly, even when the names look hierarchical. This also supports labels such as `a.1` or nonnumeric problem names.

Choose each entry's scoring mode deliberately:

| Mode | Example use | What the validator allows |
|---|---|---|
| `allowed` | Single-choice 0/1; all-or-nothing 0/4; a prescribed nonuniform set | Only the explicitly listed scores. |
| `step` | Half-point or quarter-point increments | Nonnegative multiples of the stated step, up to the item's maximum. |
| `continuous` | Fractional credit without a prescribed grid | Any finite score between zero and the maximum. |

Write the **meaning** of partial credit into the rubric and, where needed, the item's notes. A numerical mode alone does not define what deserves the points. A one-point criterion need not be binary. Conversely, a question worth several points can be all-or-nothing. The example fragments in `examples/policy_fragments/` illustrate syntax, not recommendations for adopting those policies.

Dependencies identify earlier work that can supply evidence or a result. They do not copy points or decide follow-through automatically. Explicitly state whether correct downstream work receives credit after an earlier error, and where a supplied fallback may be used. Do not import an old exam's AR/KR codes without its instructor-approved definitions.

## 4. Align PDF, manifest and instructions

The default `headings` check expects each criterion heading on its own extractable line:

```text
2.c.b - Energy conservation - 1.5 points:
```

The rule and reference equations follow that heading. Headings must have the same labels, names, maxima and order as the manifest. Repeated criterion headings in an appendix will also count, so do not duplicate them. Ordinary section headings and reference formulas are not separate criteria. A line broken across columns or an image-only heading may fail this extraction check even when it looks correct.

For a reviewed rubric that cannot satisfy the heading parser, use `rubric_validation.mode="sha256"` and put the **manually reviewed PDF's actual SHA256** in `approved_sha256`. On macOS, for example:

```bash
shasum -a 256 workspaces/my_exam/Rubrics/rubric.pdf
```

Hash approval pins the file; it does not compare its semantic content against the manifest. A person must do that comparison. In headings mode, leave `approved_sha256` empty.

Edit `Prompts/prompt.template.txt` for the examination's language and general rules. Put exam-specific exceptions in configuration notes or item notes. The supplied template handles equivalent methods, follow-through, final answers, student-written instructions, uncertainty, and the fixed JSON contract. It must not conflict with the approved rubric.

Then build and check:

```bash
python prepare_exam.py --config workspaces/my_exam/exam_config.json
python prepare_exam.py --config workspaces/my_exam/exam_config.json --check
```

The generated prompt includes the manifest, point modes and rubric hash. Do not edit that generated file directly. Change the template/manifest/notes and regenerate with `--overwrite`; the previous prompt is backed up first. This avoids the old failure mode of changing the Python item list but not the prompt, or vice versa.

## 5. Establish identity and inspect submissions

Use one PDF per complete student's submission. The default pattern accepts `Exam001`, `exam_001`, `student001`, `student_001`, or `001` as alternative filename stems. It rejects two files whose numeric IDs both mean the same exam. Leading zeros and the complete source stem are retained.

For different identifiers, change the regular expression and `identity_mode`. The pattern must contain the named group `(?P<id>...)`. This package does not identify handwriting on cover sheets, reconcile a roster, distinguish exam variants by name, or resolve duplicate identities for you. Settle those issues before scoring.

Inspect scans and use the separate PDF preflight as needed:

```bash
python normalize_exam_pdfs.py --check --input-dir workspaces/my_exam/RawExams
```

To create normalized copies from archived originals, choose a separate destination. For **unredacted simple scanner pages whose entire embedded image is intended to be visible**, the optional full-scan command is:

```bash
python normalize_exam_pdfs.py --input-dir workspaces/my_exam/Scans_original \
  --output-dir workspaces/my_exam/RawExams --full-scan \
  --report workspaces/my_exam/pdf_normalization.json
```

Do not use full-scan mode as a blanket way of revealing intentionally hidden material. After inspection, the normalized copies can live in `RawExams` while originals remain elsewhere. The scorer reads the configured directory as-is and never normalizes again. No fixed page count or A4 width is imposed.

## 6. Approve and run a controlled pilot

Confirm: source versions and key; criterion-to-part mapping; totals and allowed scores; policy consistency; complete identified scans; authorized remote processing; and the intended human-review/release process. Record those decisions outside this software. Only then set `approved_for_scoring=true` and fill the private `.env` with the approved endpoint/key/deployment.

```bash
python score_exams.py --config workspaces/my_exam/exam_config.json --check
python score_exams.py --config workspaces/my_exam/exam_config.json --exam Exam001.pdf
```

Inspect every criterion in the pilot: scores, rationales, evidence pages, omissions, and follow-through, not just a total or correlation. Include edge cases and ordinary responses. The same model settings and materials should apply to a comparison unless changing them is the explicitly documented experimental variable.

Any revised input, rubric, prompt, configuration, code or model setting requires a fresh result directory. Keep prior results, rather than silently mixing versions:

```bash
python score_exams.py --config workspaces/my_exam/exam_config.json \
  --output-dir workspaces/my_exam/evals_revision2
```

If the pilot materials/settings are unchanged and its results are acceptable for the intended workflow, running the batch in the same output directory skips the already completed matching pilot result.

## 7. Compile, review and finalize separately

```bash
python score_exams.py --config workspaces/my_exam/exam_config.json
python compile_ai_grades.py --config workspaces/my_exam/exam_config.json --require-complete
```

The default compiler can produce an interim table of available results, with warnings about missing submissions. `--require-complete` requires matching PDF/result stems; absence is never scored as zero. Use the separate human-review list for triage, retain the original JSON, and document final human decisions independently. Workbook edits are not merged back into the scoring results.

The toolkit does not convert points to an institutional grade, publish results to students, implement appeals, or import manual corrections. Those are additional course/institution responsibilities, not hidden defaults.
