# Formats and scoring rules

## Three different kinds of identifier

**Exam identifier** (`exam_id`) versions a marking specification. **Submission identifier** comes from a PDF/JSON filename, not a name inferred from the contents. **Criterion identifier** (`rubric_item`) identifies one scoreable rubric item. `part_id` groups criteria into visible question parts; `problem_id` groups those parts. Never use a page number as a substitute for a stable criterion ID.

Labels and group IDs use letters, digits, dots, underscores, hyphens or parentheses and start with a letter/digit. IDs must be unambiguous within their kind, including case-insensitive matching for review navigation. A part belongs to one problem. Group membership need not be contiguous in the manifest; the compiler sums the actual member columns.

## `exam_config.json`

All keys are required and unknown keys are rejected, catching misspellings instead of silently ignoring them. The minimal example is the authoritative executable syntax.

| Field | Meaning |
|---|---|
| `schema_version` | Integer 1 for this configuration schema. |
| `exam_id`, `exam_title` | Stable marking-version identifier and readable title. Change the ID for a different exam specification. |
| `approved_for_scoring` | Boolean guard. False allows local work but blocks live uploads. |
| `paths` | `manifest`, `rubric`, `prompt_template`, `prompt`, `exams`, `evals`. Distinct project-relative paths without `..`; paths resolving outside the project through symlinks are rejected. |
| `filename_pattern` | Regular expression matched against the entire filename **stem**, without `.pdf`/`.json`; exactly one named group, `id`. Case-insensitive. |
| `identity_mode` | `numeric` compares IDs by integer value; `text` compares case-insensitively without numeric conversion. |
| `max_combined_pdf_bytes` | Positive conservative byte cap, at most 50,000,000. The current code requires each file and the rubric/student sum to be strictly below it. Not a token limit. |
| `rubric_validation` | `{ "mode": "headings", "approved_sha256": "" }`, or `sha256` with a reviewed 64-character lowercase hash. |
| `notes` | Instructor-approved exam-specific instructions, including exceptions and conventions. Empty string is permitted. |

A configuration file's directory is its workspace root. Command-line output overrides are instead relative to the current shell directory. Keep multiple exam profiles in separate directories; this prevents accidentally sharing their `RawExams`, prompts or result folders.

## `rubric_manifest.json`

The outer object has exactly `exam_id`, `expected_total_max_points`, and the ordered `items` list. Its ID must agree with the configuration. The declared total must equal the sum of item maxima.

Each item requires:

```json
{
  "rubric_item": "2.a.b",
  "rubric_name": "Distance evaluation",
  "max_points": 1,
  "part_id": "2.a",
  "problem_id": "2",
  "score_mode": "continuous",
  "notes": "",
  "dependencies": []
}
```

`rubric_name` is a display name, not a lookup key; exact strings are retained in results. `max_points` is positive. Numerical scores are never negative in this implementation. `dependencies` is a list of other criterion IDs that supply relevant earlier work; unknown IDs, self-links and cycles are rejected. This list is documentation in the model prompt, not an arithmetic dependency engine.

Additional keys depend on mode:

```json
{"score_mode": "allowed", "allowed_points": [0, 1, 3, 4]}
{"score_mode": "step", "score_step": 0.5}
{"score_mode": "continuous"}
```

The first two are fragments, not complete entries. For `allowed`, values must be sorted, unique, within range and include zero and the maximum. For `step`, a positive step must divide the maximum. For `continuous`, no score grid is imposed. Do not provide incompatible keys for another mode. See `examples/policy_fragments/items.json`.

An MC entry can also include **both** `correct_option` and `correct_answer` as strings. For example `"2"` and `"m/s"` reduce ambiguity about printed option ordering. The code validates the presence of the pair, not the correctness of its subject matter or the student's checkbox. Include relevant figures in the rubric PDF. Different option-order versions need matching approved profiles; a positional key is not a universal answer.

## Rubric PDF heading contract

In headings mode each rubric item appears once, on one extractable line, as:

```text
2.a.b - Distance evaluation - 1 point:
```

The parser accepts optional `point`, `points`, `Punkt` or `Punkte` and the optional colon. Identifiers and maxima must match; display names are compared after Unicode normalization and whitespace removal. All following rule text and mathematical content are read by the model and reviewed by humans. The heading parser does not validate equations or resolve contradictions.

In hash mode the software pins the approved bytes, including figures and layout. It still runs the PDF geometry guard but does not extract headings. Neither mode makes OCR a prerequisite for a handwritten student exam.

## Generated `Prompts/prompt.txt`

`prepare_exam.py` combines the template with a generated block containing the exam title/ID, rubric hash, item count, point total, exam notes and every item policy. The scorer rebuilds this string locally and requires an exact match. Template/manifest changes therefore cannot quietly leave stale instructions active. Unknown scoring practices require explicit code/prompt/validator work, not an undocumented change to the output schema.

## Model result contract

This deliberately retains the specialist workflow's schema:

```json
{
  "grades": [
    {
      "rubric_item": "2.a.b",
      "rubric_name": "Distance evaluation",
      "max_points": 1,
      "awarded_points": 0.5,
      "explanation": "PDF p. 4: correct substitution; result lacks the required unit."
    }
  ],
  "human_review_recommended": false,
  "human_review_reason": ""
}
```

This is a **shape illustration**, not a complete exam result or a prescribed partial-credit rule. A real result has one grade per manifest item, in exact order, including zeros. The scorer rejects missing/extra/duplicate items, name/max mismatches, out-of-range or disallowed scores, empty explanations, NaN/infinities, duplicate JSON keys and extra fields. The compiler also accepts reordered arrays, mapping by IDs; it does not accept missing items or an older per-item review schema.

The network schema is deliberately compact, enforcing the object/array/field types. The prompt plus local validator enforce exact IDs, names, maxima, count, order and item-specific score modes. This avoids sending a large repeated per-criterion union schema to different providers. Validation does not establish that an apparently well-formed score is educationally correct.

`human_review_recommended` is an **exam-level** boolean. True requires a nonblank `human_review_reason`; false requires an empty/whitespace-only reason. Grade explanations contain one-based physical page positions in the uploaded student PDF. These are evidence references, not the printed booklet page label or rubric page. The model can be wrong about a page reference; a human should check decisive evidence.

There are no extra total, confidence, student identity, per-item flag or page-array fields. Totals are derived in the compiler. A provisional zero due to unreadability must remain associated with its review reason and is not a final human decision.

## Provenance is a separate record

`evals/Exam001.json` stays compatible with the grade contract. `evals/.provenance/Exam001.json` records a fingerprint, result hash and response metadata. The fingerprint includes source files/configuration, current code, selected installed library versions and live request settings. It excludes API keys and the raw endpoint URL. Hashes detect changes to recorded bytes; they are not signatures or proof of correctness. See [OPERATIONS.md](OPERATIONS.md) for restart behavior and limitations.

## Exports

`ai_grades.csv` is the traditional matrix: first row `Exam Number,<criterion IDs>`, second row `Maximum Points,<maxima>`, then one exam per row. No extra total or reason columns are inserted into this CSV. Numbers use decimal points and comma delimiters; UTF-8 with BOM helps common spreadsheet imports. CSV cannot force an application's import type, so import identifier columns as text to retain leading zeros. The XLSX stores identifiers explicitly as text.

`ai_grades.xlsx` adds a total, problem and part summaries, all criterion explanations, a manifest and run information. Derived totals/subtotals are Excel SUM formulas with cached values computed from the same validated snapshot. Scores are not rounded to a newly invented grid, rescaled or grade-converted. Excel's numeric precision still applies. Very long explanation strings beyond Excel's cell limit are rejected, never silently cut off.

`human_reviews.xlsx` includes a review-reference queue, an authoritative **Flagged exams** sheet and all criterion context for those exams. `human_reviews.csv` starts with `exam_number,part_id,explanation` and adds reference/source details. Extracted references are mentions in the original reason, not machine-generated item-level review decisions. Ranges and unfamiliar shorthand are not expanded. A whole-exam fallback row preserves unlocalized concerns. Every flagged exam remains in Flagged exams, including when some text cannot be mapped.

The compiler records hashes of the input result files, but does **not** validate their scoring provenance sidecars. This permits compilation of old valid results; it does not retroactively establish their model or rubric version. Use scorer checks and experiment records for that distinction. All four exports are snapshots, not live links to each other or back into JSON. Protect manual decisions separately before regenerating.
