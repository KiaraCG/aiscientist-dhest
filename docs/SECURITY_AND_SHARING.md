# Security, privacy and sharing

## What the supplied archive contains

The release contains the listed source modules, documentation, configuration templates, tests and an invented example. It includes **`.env.example` with placeholders**, not a working `.env`. The example rubric, two typed submissions and two authored result JSON files were created for this package. They are not student data and are not model-generated assessment results. Actual instructor exams, keys, scans, screenshots, rosters and grading outputs are excluded.

The archive is built from `PACKAGE_FILES.txt`, an explicit list of relative paths. It is not a recursive ZIP of the working directory. `make_shareable_zip.py` rejects forbidden path components, unexpected file types, symlinks, recognizable private-key/API-token patterns and changes to the fixed synthetic fixtures or `.env.example`. The latter checks use `SYNTHETIC_SHA256.json`, so replacing an example submission with a real student's scan under the same filename does not quietly pass the normal release command.

The builder adds an audit record and per-file SHA256 list to the ZIP. These checks establish what this archive contains and catch specific mistakes; they are not a general confidentiality detector, antivirus system, digital signature or guarantee that an arbitrary edited script contains no secret. A person can change the allowlist, fixture hash file or packaging code. Review changes before sharing.

## Build or inspect a source archive

From the toolkit root:

```bash
python make_shareable_zip.py --check
python make_shareable_zip.py --output ../exam_scoring_toolkit_share.zip
```

The destination must be outside the source directory and must not already exist. The command makes no API calls. A private `.env`, real workspace or local venv may exist on your machine, but none is picked up by the allowlist. The `.gitignore` is additional help for version control, not a ZIP exclusion rule or a secret scanner.

If a fixed example or `.env.example` was changed, restore its placeholder/synthetic version or perform a deliberate new release review before updating its approved hash. Do not suppress the check simply because an error message is inconvenient. Do not copy live values into `.env.example` and then rely on its filename to make it safe.

## Private working material

Keep API keys in the private workspace `.env` or an appropriate local secret-management mechanism. Do not include `.env`, backups of it, shell-history excerpts, provider request logs, real scans, rosters, result JSON, review spreadsheets, exports, local environment locks, `.venv`, `.git` history or editor/cloud metadata in a colleague's generic source package. A source file with a hard-coded token remains sensitive even when every `.env` file is excluded.

A roster-free exam scan can still contain names, student numbers, identifying handwriting or other personal content. A grading explanation or review reason can quote such content. Removing the cover page, renaming files or omitting a roster does not establish anonymization. The default release therefore contains **no real student material**, rather than claiming to have anonymized the provided example.

The source rubric and MC key may also have redistribution restrictions or be examination-confidential. This is why the package demonstrates the format with an invented constant-speed problem rather than copying the real course exam. Confirm rights and intended audience for any additional materials.

## Remote processing and logs

Live scoring uploads the rubric and entire student PDF to the configured provider. The source code uses a separate instruction field, requests no stored response, and attempts to delete uploaded files after use. Those controls do not replace an institutional review of authorized processing, data location, provider retention, abuse monitoring, access controls or contracts. See the vendor references; do not infer zero retention from `store=false`.

The scorer does not print API keys, stores no raw `.env`, omits key hashes, hashes endpoint resource names in provenance and redacts the configured key in caught per-exam failure messages. This is not a guarantee against every SDK, proxy or shell logging configuration. Deployment names, file stems, review reasons and provider response IDs are still potentially sensitive operational records. Keep them with the private experiment, not in the shared generic ZIP.

The normalizer is not a redaction utility. Full-scan mode may reveal pixels that page boxes had hidden. It cannot certify that hidden text, annotations or other content has been removed. Encrypted PDFs, forms/signatures and annotations need separate handling; do not flatten them blindly just to satisfy a preflight check.

## No authority over institutional policy

The `approved_for_scoring` boolean is an operator checkpoint, not authentication, consent collection, a legal finding or permission to upload student work. The software does not determine whether a particular exam, institution or jurisdiction permits the workflow. The responsible institution must settle that before live processing and before sharing real materials.
