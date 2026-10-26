# Architecture, retained mechanisms and new changes

## The stable core

The supplied scripts used a practical whole-exam workflow: approved marking content and a complete scanned submission are sent as two PDF inputs, rubric first. A structured response contains one score per criterion, and deterministic local code validates and compiles it. Identification, marking-policy approval and final review remain outside the model call.

This package adapts that source rather than presenting a different pedagogical system. The standalone PDF normalizer is carried over from the current preflight utility. The compiler is adapted from the current FKP compiler. The scorer preserves the familiar request order, local inspection, cleanup, strict validation and local worker coordination, while refactoring the exam-specific item list and policy rules into configuration. Earlier specialist scripts and actual source exam PDFs are not bundled as competing executables.

## Where to make a change

| Need | Change here | Also verify |
|---|---|---|
| New criteria, names, maxima, grouping | `rubric_manifest.json` and approved rubric PDF | Regenerate prompt, check totals/headings, pilot. |
| Binary, discrete or fractional scores | Entry's `score_mode` and matching rule text | Result validator and compiler use the same entry; no Python edit ordinarily needed. |
| Follow-through or another convention | Approved rubric plus item/config notes | Model instructions, edge-case pilot responses; dependencies alone grant no points. |
| Different file IDs/prefixes | `filename_pattern`, `identity_mode` | Duplicate handling, joins and downstream export expectations. |
| Changed exam-level wording/language | Prompt template and notes | Regenerate prompt, new output directory for changed experiments. |
| Scanned/non-extractable rubric | Explicit reviewed SHA256 mode | Human verifies criterion correspondence; geometry guard still applies. |
| A different provider/authentication API | `score_exams.py` settings/upload/request adapter | File purpose, endpoint, schema, parameters, storage, cleanup, failures and live pilot. |
| A different result schema | `exam_common.py`, scorer, prompt and compiler | Version all consumers; do not silently accept multiple incompatible meanings. |
| A different human-review workflow | Process documentation and appropriately separated outputs | Blinding, provenance, source authority and final decision records. |

No filenames, manifests or totals from the real FKP exam are embedded in the generic engine. The invented example is intentionally much smaller, with five criteria and mixed scoring modes, so assumptions about 69 items, five problems or half-point rounding are exposed by tests.

## New behavior, not a claim about the old code

**Configuration is authoritative.** Earlier scripts duplicated the manifest inside Python and the prompt, sometimes also in a JSON export. The generic package has one required JSON manifest consumed by preparation, scoring and compilation. The generated prompt is derived from it and checked byte-for-byte at runtime.

**The network schema is smaller.** Rather than generating a large per-item union, it defines the shared grade object and review fields. The local validator enforces the exact item count/order/strings and numerical modes. It rejects invalid outputs; it does not repair them using another model. This makes the local checks essential, not redundant.

**Resume now checks provenance.** Source results remain in the old three-field object, with metadata kept in `.provenance/`. A missing/mismatched record blocks reuse instead of merely skipping valid-looking JSON. There is intentionally no automatic adoption of older results or overwrite flag for scoring. Use a fresh experiment directory.

**Live uploads need an explicit local approval boolean.** This prevents the distributable synthetic example from accidentally becoming a real paid run. It does not authenticate an approver or enforce institutional policy.

**Filename and score modes are configurable.** The code supports arbitrary positive maxima with `allowed`, `step` or `continuous` nonnegative scoring and explicit group IDs. It does not infer instructor intent from a maximum value or from an AR/KR abbreviation.

**An optional direct OpenAI adapter is included.** The Azure path retains the established variables and `/openai/v1/` convention. Provider compatibility is checked against documented request patterns, not certified by live calls in this release.

**Review-reference mapping is generic and deliberately limited.** Literal configured IDs, numeric parenthesized part aliases, and explicit whole-problem phrases are mapped. Shorthand ranges are not expanded. The full reason and every actual flagged exam are retained, so the code never pretends to reconstruct a structured item-level flag from prose.

**Inventory failures are fail-closed.** In the scorer, unknown PDF filenames and duplicate identity groups block the selected run before uploads, instead of silently ignoring an ambiguous exam. The compiler rejects invalid result inventories. An incomplete optional PDF inventory can be a warning for an interim export; `--require-complete` makes it a blocking condition.

## Deliberately outside this package

There is no learner model, autonomous tutor, learning-management-system integration, roster recognition, cover-sheet handwriting recognition, batch page splitter, web review interface, blind-rescoring packet generator, final-grade conversion or manual-score merge. It is not an installer for EthelFlow/EthelExam or an institutionally approved deployment service.

Native Windows locking, distributed workers across hosts, stateful provider conversations, provider-hosted batch jobs, arbitrary "OpenAI-compatible" gateways, negative marking, optional-question selection rules, best-N-of-M totals and conditional rubric maxima are not implemented. A configured subset can be scored, but merging separately authoritative MC/other scores needs an explicit downstream design. Tests should be added when extending these boundaries.

## Test boundary

Offline tests exercise configuration/score validation, exact IDs, mixed score modes, PDF geometry, unchanged image streams, synthetic request structure, cleanup, provenance mismatches, interruption detection, resume, spreadsheet outputs and overwrite protection. Provider responses in those tests are fake objects, not remote model scores.

The synthetic PDFs are typed. They neither establish handwriting-reading quality nor reproduce every physical scanning defect. A local grade table with correct formulas is not evidence that its source scores are correct. Keep those distinctions explicit when sharing the package with colleagues.
