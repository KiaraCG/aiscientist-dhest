# Human review and responsibility

This toolkit generates provisional criterion scores plus explanations. It does not make institutional final-grade decisions, implement appeals, or decide which student should pass. The local approval flag and software validation are operational controls, not substitutes for instructor responsibility.

## What is actually flagged

The current result schema stores `human_review_recommended` and `human_review_reason` once per exam. Every criterion still has a numeric score and its own evidence explanation. A true exam flag means a material issue needs human attention; it does not mean every criterion is wrong or that the model has identified all possible errors.

The supplied template distinguishes ordinary wrong/blank work from decisive unreadability, missing evidence, ambiguous final selections, uncertain question matching and unresolved rubric/convention conflicts. The exact circumstances and provisional-scoring policy remain instructor decisions. Do not use fractional scores as confidence estimates or infer that a review flag is a calibrated probability of error.

## Reading the generated workbook

The **Flagged exams** sheet is the authoritative list of the actual source flags and full reasons. The **Review queue** is an index of literal references found in those reasons. A criterion mention becomes a criterion-reference row; a part mention remains a part-reference row. Whole-problem mentions can also be indexed. If nothing can be localized, an EXAM row keeps the concern visible.

This mapping is intentionally not another AI call. It does not reliably understand negation, all prose references, compressed ranges, or which clause a reference belongs to. An item might be mentioned as an earlier dependency. Read the entire reason and verify the affected scope. When some references are recognized and other concerns are not, the full reason and the Flagged exams entry still preserve those concerns.

The **All criteria** sheet supplies context for flagged exams; those rows are not all individually flagged. Scores and explanations remain tied to source JSON and submission stems. Page numbers inside a model explanation are not a trusted independently measured page map.

## Triage versus independent rescoring

For operational triage, a reviewer may need the model's stated uncertainty and page reference to find a questionable scan, mark or convention. The generated review workbook is suitable for that purpose.

An independent, blinded rescore is a different task. A packet intended to avoid exposing the reviewer to AI scores or reasoning should contain the relevant student evidence and approved rubric **without this workbook's score/reason context**. If a veto/appeal mechanism requires independent rescoring, prepare the corresponding blinded materials separately. This toolkit does not create or serve that packet automatically.

Do not call a process blinded merely because a reviewer is different from the original operator. The workbook has the AI's output in it. Likewise, a model's own review recommendation is not the same thing as an instructor/student veto or an independent error audit.

## Suggested pilot and release checks

Before batch adoption, have subject-matter reviewers inspect complete pilot responses, including correct, partially correct, blank, alternate-method and difficult-to-read work. Examine the rubric-level disagreements and reasons, not only total-score correlations. Resolve ambiguities in the specification before applying it consistently to the cohort. These are recommended operating checks, not implemented evaluation metrics.

Include a deliberate sample of unflagged work in quality review. The fraction flagged or the agreement of the final score with the initial AI score alone is not a measurement of error sensitivity, false negatives, or independent scoring accuracy. This package does not calculate psychometric validity, grader reliability, uncertainty calibration or time savings.

Record final human decisions in a controlled separate artifact with submission/criterion IDs, original score, revised score, reason, reviewer and date as appropriate to the institution. Preserve raw AI JSON and its provenance. The current compiler does not read a manual-corrections file or merge workbook edits; regenerating exports will not carry those changes forward.

Ensure students and staff receive the applicable instructions about assessment and review through the institution's own process. No claim of compliance with any particular law, policy, consent requirement or examination regulation is made by this source package.
