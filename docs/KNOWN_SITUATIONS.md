# Situations encountered, and how to adapt rather than guess

These cases come from the supplied specialist workflow and its investigations. The responses below distinguish preserved mechanisms from new configurable choices. The real papers, answer keys and student scans used during those investigations are deliberately not distributed here.

## Separate question sheet and rubric; no multiple-choice key

A rubric consisting of abstract scoring criteria may omit the actual problem, figure, reference data or options. A student scan then becomes the only accidental source of those facts. Combine the authoritative questions/figures with the criteria; check variant and option order. Obtain a confirmed MC key from the instructor or a verified matching answer sheet. A student's tick, a plausible calculation or a guessed answer is not an approved key.

In the earlier solid-state example, an older matching marked answer sheet supplied the absent MC key, while the newer rubric remained authoritative for open responses. That was a source-precedence decision for that exam, not a rule that older solutions always outrank newer criteria. Record provenance and resolve disagreements with the instructor. This package supplies only an invented key for its toy demonstration.

## An old scorer carries a different exam inside it

A previous mechanics script embedded 24 one-point criteria and a particular filename pattern; the later solid-state exam used 69 criteria totaling 53, including half-point maxima and MC. Reusing the same filename `score_exams.py` did not make the manifests interchangeable.

The generic version moves labels, names, maxima, groups and numerical score modes into one shared JSON manifest. The prompt is generated from it, and both scorer and compiler use it. Changing only a top-level total is not enough. Keep a separate profile for each exam and marking version. Duplicate array entries, name mismatches and absent criteria fail validation rather than being coerced into the new structure.

## Same appearance, different PDF geometry

There were two distinct cropping situations.

First, an earlier group of scans stored landscape page boxes with alternating 90/270-degree rotation metadata. Conversation previews omitted parts of pages although local complete renders retained them. A rotation/preprocessing interaction was a hypothesis; the exact Azure preprocessing cause was not demonstrated. Applying `transfer_rotation_to_content()` to contents and page boxes, then clearing rotation, reduced that metadata dependency. Merely deleting `/Rotate` would not correctly orient the underlying content.

Second, a later upright scan had matching MediaBox/CropBox yet its placed image extended to x=602.10 points while the page ended at 595.32. A 6.78-point strip, about 2.39 mm, was outside the visible right boundary. Rotation-only checking would miss it. It did not by itself establish that an important answer lay in that strip. Explicit full-scan normalization grew the page to contain the complete existing scan; it did not create missing handwriting or enhance faint ink.

The distributed normalizer retains both mechanisms and uses synthetic tests for rotations, nonzero origins, intentional crops and image overhang. It neither forces A4 nor recompresses the scan images. The full-scan check understands simple single-image placement, not arbitrary graphics/clipping paths. Cropping is not redaction: intentionally hidden content can still exist in a PDF. Only reveal the full image when authorized and intended. Verify outputs visually and on the selected inference path; geometry tests do not guarantee proprietary rendering.

## Faint writing, blank work and actually missing pages

A blank response is different from illegible evidence. A header near the edge or a very short answer is not proof of cropping. The prompt asks the model to read all available pages, use legible evidence and flag decisive uncertainty without inventing symbols. A provisional score on unreadable work is not a final grade. Preflight does not suppress a genuine human-review flag.

PDF page count is not a roster or completeness proof. A readable 27-page file can contain the wrong student's page, a duplicate page or a missing original that was replaced by another sheet. Use your scanning/identification controls independently. The toolkit does not infer identities from cover handwriting.

## Answers on extra pages or under another part

Whole-exam input permits explicit cross-references and content-based matching across all pages. The final letter of a rubric ID may label a criterion, not another question. Page-map hints are orientation aids, not instructions to ignore everything elsewhere. The prompt requests physical PDF page references inside explanations. No fixed page count is imposed.

For a separate paper-per-problem workflow or a fixed authoritative answer sheet, define that different evidence scope explicitly. Page splitting and identification are not automatically implemented by this toolkit. Do not assume a cut-out contains enough context for follow-through from earlier work.

## Equivalent derivations and follow-through

The supplied rubrics emphasize demonstrated content rather than a prescribed sequence of intermediate equations. A concise vector expression can satisfy several distinct component criteria; a correct combined equation may demonstrate a relation without separately writing it first. This is not permission to award multiple criteria for vague evidence or to invent absent reasoning.

An earlier arithmetic/sign/degeneracy error need not be charged again for a later mathematically correct operation based on it. Conversely, a new independent error can lose separate credit. Some exams explicitly allow a fallback dispersion or value in later parts, without crediting that fallback as a solution of the earlier derivation. Encode those distinctions in the actual criterion wording and item notes. `dependencies` does not automatically grant or remove points.

AR/KR were course-specific metadata in an earlier mechanics implementation. Their detailed semantics are not established as a universal standard by this package. Do not use unexplained abbreviations in a generic prompt; write the approved requirements and follow-through behavior in full.

## Conflicting reference values or conventions

The source solid-state rubric retained instructor-check notes and accepted both printed thermal-conductivity benchmarks and consistent recalculations from the provided inputs. It also clarified use of a positive absolute-value exchange coefficient where an older solution's notation was inconsistent. These are examples of **explicit approved allowances**, not instructions to let a model silently repair every rubric.

When a student uses another physically consistent convention, compare against the rubric's allowed alternatives. A substantive unresolved conflict should be reviewed. Do not add a new criterion such as a particular notation, energy zero or intermediate line unless it was part of the intended marking scheme. Generic software cannot decide whether an instructor intended a global sign convention or a particular physical assumption.

## Marked, crossed-out and replaced choices

A final unambiguous replacement is not two independent selections merely because an abandoned box still has a mark. Ordinary cross-references, scratchwork and statements like "the answer is c" are answer content, not prompt injection. If final intent is genuinely unclear, do not infer that the student chose the keyed answer. Follow the approved provisional-score and review rule.

Some previous exams used a separate authoritative bubble sheet and excluded MC from the AI script entirely. Others scored the visible exam choices. Choose one authority deliberately. A subset manifest should contain only the AI-scored items and its subtotal, with explicit exclusions in the rubric/prompt. The compiler does not merge an external MC score table automatically or infer a complete-exam total from a subset.

## Student instructions aimed at the model

Treat student content as evidence rather than instructions to change the role, grading policy, scores or JSON schema. Do not introduce a new misconduct deduction just because a prompt-like sentence appears. Score demonstrable work under the approved rules and flag material manipulation concerns for the institution's process. The separation of instructions and student input is a defense, not a proof against all adversarial behavior.

## Human review exists only at exam level in the current schema

The compiler must not fabricate per-criterion flags from the fact that an exam is flagged. It preserves the full reason and maps recognized literal item/part references as navigation aids. A reason may mention a previous part as context, not because that part itself is disputed. Unrecognized shorthand/ranges stay visible in the reason; a Flagged exams row is never dropped.

A low score is not an automatic reason for human review. Nor does an unflagged score certify correctness. The review workbook is not a blinded independent-rescoring packet because it includes AI scores/reasons. See the dedicated human-review guide.

## Complete JSON, but produced by yesterday's inputs

The old resume mechanism checked completeness/schema only. The new generic mechanism adds separate input/settings fingerprints. A changed PDF, rubric, prompt, code, manifest, library version or configured model blocks reuse and asks for a fresh output directory. Do not combine mixed revisions merely because their arrays share the same labels.

The compiler records result-file hashes but deliberately can also compile older valid JSON without sidecars. This is a compatibility feature, not proof of its provenance. A changed backend under an unchanged deployment label remains outside what local file hashes can establish.

## A valid-looking workbook hides missing or truncated results

Never turn absent JSON or missing criteria into zero scores. By default the compiler shows available results and warns about missing matching PDFs/results; `--require-complete` blocks a final export until the inventory matches. Duplicate identities or invalid result records fail rather than being summed twice. Source explanations and human-review reasons are preserved, and overlong Excel cells cause a clear error rather than text truncation.

CSV does not carry cell types. Preserve zero-padded identifiers by importing as text or use the XLSX, where the type is explicit. Numeric-looking headings, decimal conventions and formula-like source text can be misread by spreadsheet applications. The compiler uses literal text cells and CSV prefix protection rather than executing source text as a formula.

## Model/context limits and non-rubric experiments

A larger output token cap is not a substitute for correct PDF rendering. A local geometry pass is not a test of the deployment's context capacity. Test one complete submission first; diagnose unsupported parameters, rate limits and incomplete responses before bulk runs. There is no automatic model fallback, unannounced OCR route, or silent dropping of pages.

Past experimental work sometimes deliberately scored without a reference solution/rubric. That is a different experimental condition. The current generic package requires an approved rubric and corresponding manifest. Do not rename a bare question sheet to `rubric.pdf` and claim that the same validation and educational assumptions still hold. Such an experiment needs a separate explicit prompt and validation design.
