# Sources and provenance of this package

## Supplied workflow sources

The starting point was the set of standalone scripts and examination materials supplied in the conversation, not a formally versioned upstream software release. The real exam documents and student scans are deliberately **not included** in this archive.

- Earlier mechanics `score_exams.py` (24 criteria): the two-PDF Azure request pattern, established environment variable names, five fields per criterion, exam-level review flag, per-exam locks and restart behavior. Its AR/KR metadata and point restrictions were exam-specific, not adopted as generic rules.
- Current FKP `score_exams.py` (69 criteria, 53 points): full-exam handling, local PDF guard, numeric identity/filename conventions, review explanations with page references and schema-only historical resume warning.
- Current `normalize_exam_pdfs.py`: the standalone rotation/origin and optional full-scan geometry utility. This source was reused without functional changes. Its original synthetic geometry tests are included.
- Current FKP `compile_ai_grades.py` and `README_COMPILE.txt`: two-header-row CSV score matrix, score/part/problem explanatory XLSX views, preservation of full exam-level review reasons, literal reference navigation, input validation and protected export replacement.
- Supplied solid-state question sheet and rubric: examples of separate authoritative question/rubric sources, MC-key provenance, method-independent criteria, permitted fallback expressions, follow-through, accepted numerical alternatives and instructor-check notes. They motivate the adaptation guide; their actual criteria, questions and key are not shipped.
- The preceding PDF investigations: a rotation-related preview problem with an unconfirmed inference-backend cause, and a separate simple-scan right-edge overhang. The generic docs retain the distinction between an observed local/preprocessing issue and an unverified explanation of a provider's internals.

The common configuration module, prompt preparation command, synthetic example, explicit approval guard, provenance sidecars, direct OpenAI adapter and allowlist release builder are **new additions/refactorings for this package**. They are not retrospectively attributed to the earlier scripts. The generic review mapper recognizes a narrower set of literal forms rather than claiming a universal natural-language interpretation.

## Vendor and runtime documentation

The following primary documentation was consulted during preparation on 2 October 2026. Service capabilities, limits and SDK versions can change; verify the deployed combination before a live pilot. Source links document API/format behavior, not educational effectiveness.

1. [Microsoft: Azure OpenAI Responses API](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses) - v1 endpoint, PDF inputs, upload-purpose distinction and provider-specific capability requirements.
2. [OpenAI: File inputs](https://developers.openai.com/api/docs/guides/file-inputs) - PDF text/page-image processing, upload/file references, byte limits and optional PDF image detail.
3. [OpenAI: Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs) - response-schema structure and supported constraints. A well-formed response is not proof of a correct assessment.
4. [pypdf: Cropping and transforming PDFs](https://pypdf.readthedocs.io/en/stable/user/cropping-and-transforming.html) and [PageObject reference](https://pypdf.readthedocs.io/en/stable/modules/PageObject.html) - content transforms, page boxes and rotation handling; cropped content can remain recoverable.
5. [Python: venv](https://docs.python.org/3/library/venv.html), [fcntl](https://docs.python.org/3/library/fcntl.html) and [os](https://docs.python.org/3/library/os.html) - environments and the local operating-system primitives used by the scripts.
6. [openpyxl documentation](https://openpyxl.readthedocs.io/en/stable/) - workbook writing/reading. The compiler calculates its known SUM caches from validated data; it is not a general Excel calculation engine.
7. [Microsoft: Azure Direct Models data, privacy and security](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy) - consult the applicable service/deployment terms rather than treating local flags as a retention or compliance guarantee.

No claim of independent model accuracy, psychometric validation, institutional endorsement or production service certification is made. Offline test results are documented separately in `VALIDATION.md`.
