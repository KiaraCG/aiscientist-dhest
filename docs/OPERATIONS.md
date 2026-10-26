# Operations: environment, requests, restarts and failures

## Environment

Keep the toolkit modules together. A virtual environment belongs to the Python installation; `.env` is a separate, private credential/configuration file. Create a new environment only when needed:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Existing working environments need not be upgraded just to inspect this package. Its runtime dependencies are `openai`, `python-dotenv`, `pypdf` and `openpyxl`. `reportlab` is optional, for regenerating the invented example PDFs through `requirements-dev.txt`. There is no runtime requirement for OCR, a GPU, LaTeX, Poppler, pandas or a local model. The supplied dependency ranges are not an exact lock or proof of compatibility with every future release in those ranges.

After a successful pilot, record the exact local environment privately:

```bash
python -m pip freeze > requirements.lock.txt
```

Do not publish that file blindly: local dependency URLs can contain internal paths or credentials. The release packager deliberately does not include it.

## Azure configuration and the optional direct adapter

Copy the supplied `.env.example` into the private workspace as `.env`. The Azure route preserves the established variable names:

```dotenv
SCORING_PROVIDER=azure
AZURE_OPENAI_ENDPOINT=https://YOUR-RESOURCE.openai.azure.com/
AZURE_OPENAI_API_KEY=REPLACE_ME
AZURE_OPENAI_DEPLOYMENT=REPLACE_ME_WITH_DEPLOYMENT_NAME
AZURE_OPENAI_REASONING_EFFORT=high
AZURE_OPENAI_MAX_OUTPUT_TOKENS=30000
AZURE_OPENAI_TIMEOUT_SECONDS=900
SCORING_MAX_RETRIES=2
SCORING_PDF_DETAIL=
```

The placeholder values do not authorize a call. Live scoring loads `.env` from the selected configuration file's directory, with existing exported shell variables taking precedence. Local `--check`, preparation, PDF utilities, compilation and the demo do not load it.

The Azure endpoint can be the resource root or end in `/openai/v1/`; other paths, non-HTTPS URLs, credentials in URLs, fragments and query parameters are rejected. API-key authentication is implemented. Entra/managed-identity authentication, arbitrary compatible gateways and proxy-specific parameters are not implemented here; adapt and test rather than assuming the same URL convention.

The optional direct OpenAI route is newly added, not evidence of a previous deployment. Set `SCORING_PROVIDER=openai`, `OPENAI_API_KEY`, `OPENAI_MODEL`, and the corresponding `OPENAI_REASONING_EFFORT`, `OPENAI_MAX_OUTPUT_TOKENS` and `OPENAI_TIMEOUT_SECONDS` variables. Its endpoint is fixed to the public API. Azure uses the configured deployment name, not an automatically substituted model. Neither route falls back to a different model or provider.

The selected model/deployment must support the combination of PDF vision inputs, Responses, structured JSON and any specified reasoning/detail options. An empty reasoning-effort value omits that parameter. `SCORING_PDF_DETAIL` is omitted when blank; use `auto`, `low` or `high` only after checking support on the selected endpoint. Reasoning effort and PDF image detail are different controls. Neither repairs bad source geometry.

Vendor details were checked against the references in [REFERENCES.md](REFERENCES.md). Those documents can change. The implementation uses Files purpose `assistants` for Azure and `user_data` for direct OpenAI. The combined PDF byte cap is not a token/context cap; even files below it can exceed the model's available context or output budget.

## Request and response lifecycle

The scorer validates the configuration, generated prompt, rubric, selected submission inventory, PDF geometry and existing results before its first paid request. It then uploads one rubric per process and one full submission per exam. It sends the exact inspected PDF bytes. There is no three-page or fixed-booklet-length assumption.

The rubric is File 1, the student submission File 2. The complete generated prompt is the request's instructions. The request uses `store=false`, disables automatic input truncation, and asks for strict structured JSON. Neither that flag nor file deletion constitutes a blanket data-retention or privacy guarantee; institutional service configuration and agreements still matter.

An explicit message distinguishes the upload from the subsequent non-streaming wait. There are no incremental model tokens, heartbeat or reliable progress percentage. The response must be completed, nonempty, non-refused, parseable and locally valid. The program never fills missing criteria with zero, rounds disallowed scores into acceptance, repairs JSON using another model, or substitutes a fallback deployment.

Uploaded student files are deleted in `finally`; the rubric upload is deleted after the process finishes. Failures are reported, not hidden. A killed process or lost Files API response can leave an upload without a locally recorded ID. Cleanup is best effort, not a retention guarantee; inspect provider storage under your operational policy.

## Preflight and the boundary of its claims

`score_exams.py --check` is read-only and performs no API calls. It checks current file/code fingerprints against existing sidecars but deliberately does not read credentials, so it **cannot compare the intended current provider/model request settings**. The live path compares those settings as well before skipping results.

`normalize_exam_pdfs.py --check` is also local. It reports page boxes, rotation, origins, user units and, for recognized simple image pages, scan-placement bounds. Complex vector/text/form content is not given an invented full content-bounds guarantee. The scorer refuses detected problematic geometry, unsupported forms/annotations or nonstandard conditions; it does not offer an automatic bypass that hides missing content.

Passing any preflight is not proof of scan legibility, correct student identity, complete capture, sound marking criteria or correct scores. Inspect representative complete pages and test the chosen model with a controlled pilot. The loss of pixels before PDF creation cannot be repaired by metadata normalization.

## Resume: intentionally stricter than the old specialist scripts

For each result the new scorer writes:

```text
evals/Exam001.json
evals/.provenance/Exam001.json
```

The first file retains the established grade schema. The sidecar stores a result SHA256 and the configuration, manifest, rubric, prompt, submission and code hashes, Python/dependency versions, selected request settings and response metadata. No key, key hash or raw `.env` is recorded. The endpoint itself is hashed; deployment names and response IDs can still be operationally sensitive.

Existing results are skipped only when valid and their recorded fingerprint matches. A change to any recorded input, code, environment version or live setting blocks reuse. Even a harmless whitespace change to a configuration file changes its byte hash. This is deliberately conservative, not semantic equivalence checking.

Use a new directory for a changed experiment:

```bash
python score_exams.py --config workspaces/my_exam/exam_config.json \
  --output-dir workspaces/my_exam/evals_run2
python compile_ai_grades.py --config workspaces/my_exam/exam_config.json \
  --evals-dir workspaces/my_exam/evals_run2 --output-dir workspaces/my_exam/compiled_run2
```

The configuration's default evals path does not change merely because a command used an override. Pass the same override when checking/compiling that run.

Older JSON without sidecars can be compiled if its manifest/schema match, but is not silently trusted for scoring resume. Do not invent sidecars that claim knowledge of old model settings. Preserve old results and use a fresh output directory for a new controlled run. Review-flagged results are completed scores for resume purposes, not automatic requests for repeated model calls.

A matching fingerprint does not detect an unannounced backend change under the same deployment name and does not guarantee determinism. It also cannot prove that the recorded rubric was actually approved or that an external operator did not alter both a file and its sidecar. Preserve independent experiment records where needed.

## Interruptions, locks and paid retries

Each result and its sidecar is published as a complete, no-overwrite file. They are not a two-file database transaction. The sidecar is the completion marker: interruption after result publication but before the sidecar leaves an ambiguous pair which is detected on restart. Preserve it and resolve the incident explicitly; the script does not silently discard evidence and pay for another call.

On macOS/Linux, workers use persistent advisory lock files under `evals/.locks`. Several terminals can run the same command against the same unchanging inputs and settings on the same local filesystem. Each worker takes an exam lock, rechecks the result, and skips a busy/completed exam. Do not delete lock files while workers run: different inodes can defeat the coordination. A crashed process releases its operating-system lock even though the lock file remains.

Do not run different manifests, prompts or script versions into the same output directory. Do not assume local locks coordinate across separate hosts, cloud synchronization tools or arbitrary network filesystems. There is no distributed queue, database lease, exactly-once billing guarantee or automatic batch scheduler.

SDK retries are configured separately from result validation. A timeout can occur after a provider accepted work, so a retry or manual rerun may incur another request even though no result was saved locally. There are no automatic corrective model calls after an invalid grading response. For quota errors, unsupported parameters, context limits or incomplete outputs, stop and diagnose before launching many processes. Increasing the output cap can address output exhaustion within deployment limits; it does not recover missing scan content.

## Compiler publication

The compiler reads each input JSON into a validated snapshot. It stages all four exports, checks that source JSON hashes have not changed, and publishes the files under a local writer lock. Existing exports require `--overwrite`; previous versions are copied into `.compile_backups/<run-id>/`. Ordinary exceptions during publication trigger rollback where possible.

Four separate output files are not an all-or-nothing filesystem transaction against process termination or power loss. Workbook run IDs and source hashes help detect a mixed export; regenerate from preserved JSON after an interruption. Do not compile into a directory being edited in a spreadsheet application, and do not treat workbook edits as amendments to the original scoring JSON.

No-model utilities generally return 0 on success and 1 on detected failure. PDF normalization additionally uses 2 for attention/review needed; command-line argument errors also use 2. Check the actual message rather than interpreting every nonzero exit as a corrupt scan. A partially completed normalization batch may have written some valid copies; originals remain unchanged.
