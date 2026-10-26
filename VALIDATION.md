# Validation of this release

## What was tested

The shipped test suite exercises synthetic configurations and submissions, local result validation, PDF normalization and the read-only guard, prompt preparation, request construction against fake provider clients, upload cleanup, resume fingerprints, interruption handling, exports and release packaging.

The known synthetic scores are six and four points out of six. Workbook tests independently check the score-matrix cells, formulas and cached totals, preservation of leading zeros, full review reasons, unlocalized exam flags, literal formula-like text, fractional credit, noncontiguous group totals, protected overwriting and source preservation. PDF tests verify normalizing rotations/origins, recognizing simple-scan overhang, maintaining encoded image streams and refusing unsafe cases.

**All 100 offline unit tests passed in the base environment.** The release audit verifies the exact archive file list, placeholder-only environment example against its approved hash, fixed synthetic example bytes, exclusion of working environments and symlinks, and selected recognizable secret patterns. It does not establish general confidentiality of arbitrary future changes.

Run locally:

```bash
python -m unittest discover -s tests -v
python run_demo.py --output-dir demo_check
python make_shareable_zip.py --check
```

The example PDF pages and generated workbook views were also inspected locally. The package contains the reproducible fixture source and tests, not screenshots of real student pages.

## What was not tested or established

No live Azure or OpenAI inference was performed for this release. API behavior was exercised using simulated clients; the source was checked against the linked provider documentation. No deployment availability, quotas, remote rendering, model grading quality, handwriting recognition, network-filesystem coordination or institutional/legal compliance is certified.

The invented typed submissions are not a validation set for a real examination. No actual student-result spreadsheets are included. A successful offline demo validates the plumbing and numerical aggregation for those fixtures, not the educational judgments of a model.

The base local test environment used Python 3.13.5, pypdf 5.9.0 and openpyxl 3.1.5; ReportLab 4.4.9 was used only to author the example PDFs. Runtime dependency files specify ranges, not a pinned lock. Rerun the tests in the intended environment and conduct a controlled model-side pilot before real scoring.

A fresh dependency-installation check could not be completed because the build environment could not resolve the package repository. The OpenAI SDK was not installed there; actual SDK serialization/HTTP integration and the latest allowed pypdf version were therefore not tested. This is separate from the passing fake-client/unit tests and is a reason to repeat installation and pilot checks in the intended environment.
