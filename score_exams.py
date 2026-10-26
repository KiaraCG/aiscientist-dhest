#!/usr/bin/env python3
"""Score whole exams with two PDF inputs and the shared configurable manifest.

Default layout: Rubrics/rubric.pdf, Prompts/prompt.txt, RawExams, evals.
Paths are relative to exam_config.json, not to this script or the shell cwd.
No OCR, PDF conversion or normalization is performed by this scorer.

Run --check first. Live scoring requires approved_for_scoring=true. Existing
scores are skipped ONLY when valid and matched to a provenance sidecar. Use a
fresh --output-dir for changed inputs/settings; old source JSON is never edited.
The contract remains grades + exam-level human_review_recommended/reason.
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.metadata
from pathlib import Path
import os
import sys
import time
from typing import Any
from urllib.parse import urlsplit

from exam_common import (VERSION, Config, ExamError, discover, generated_prompt,
                         json_bytes, load_config, load_json, output_schema,
                         sha256, strict_loads, validate_result, write_new)
from pdf_inputs import PDFInput, check_pair, read_pdf, validate_rubric


@dataclass(frozen=True)
class Settings:
    provider: str
    endpoint: str
    deployment: str
    effort: str
    max_tokens: int
    timeout: float
    retries: int
    pdf_detail: str
    api_key: str = field(repr=False)

    def public_record(self) -> dict[str, Any]:
        # No API key, key hash, or raw .env text is recorded. Endpoint is hashed
        # because resource names may themselves be internal information.
        return {"provider": self.provider, "endpoint_sha256": sha256(self.endpoint.encode()),
                "deployment": self.deployment, "reasoning_effort": self.effort,
                "max_output_tokens": self.max_tokens, "timeout_seconds": self.timeout,
                "sdk_max_retries": self.retries, "pdf_detail": self.pdf_detail}


def required_env(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value or "REPLACE_ME" in value or "YOUR-" in value or "YOUR_" in value:
        raise ExamError(f"Configure {key}; placeholder or empty values cannot be used")
    return value


def azure_base_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ExamError("Azure endpoint must be an HTTPS resource URL without credentials/query/fragment")
    if parsed.path.rstrip("/") not in ("", "/openai/v1"):
        raise ExamError("Azure endpoint must be a resource root or end in /openai/v1/")
    return f"https://{parsed.netloc}/openai/v1/"


def settings(root: Path) -> Settings:
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise ExamError("Install requirements.txt in your venv") from exc
    load_dotenv(root / ".env", override=False)
    provider = os.getenv("SCORING_PROVIDER", "azure").strip().lower()
    if provider not in ("azure", "openai"):
        raise ExamError("SCORING_PROVIDER must be azure or openai")
    prefix = "AZURE_OPENAI" if provider == "azure" else "OPENAI"
    key = required_env(prefix + "_API_KEY")
    endpoint = azure_base_url(required_env("AZURE_OPENAI_ENDPOINT")) if provider == "azure" else "https://api.openai.com/v1/"
    deployment = required_env("AZURE_OPENAI_DEPLOYMENT" if provider == "azure" else "OPENAI_MODEL")
    effort = os.getenv(prefix + "_REASONING_EFFORT", "high").strip()
    try:
        max_tokens = int(os.getenv(prefix + "_MAX_OUTPUT_TOKENS", "30000"))
        timeout = float(os.getenv(prefix + "_TIMEOUT_SECONDS", "900"))
        retries = int(os.getenv("SCORING_MAX_RETRIES", "2"))
    except ValueError as exc:
        raise ExamError("Invalid numeric token/timeout/retry setting") from exc
    if not max_tokens > 0 or not 0 < timeout <= 86400 or not 0 <= retries <= 10:
        raise ExamError("Positive token cap and finite timeout <=86400 required; retries must be in 0..10")
    detail = os.getenv("SCORING_PDF_DETAIL", "").strip().lower()
    if detail not in ("", "auto", "low", "high"):
        raise ExamError("SCORING_PDF_DETAIL must be blank, auto, low or high")
    return Settings(provider, endpoint, deployment, effort, max_tokens, timeout, retries, detail, key)


def code_fingerprint() -> dict[str, str]:
    root = Path(__file__).resolve().parent
    return {name: sha256((root / name).read_bytes()) for name in
            ("score_exams.py", "exam_common.py", "pdf_inputs.py", "normalize_exam_pdfs.py")}


def library_versions() -> dict[str, str]:
    result = {"python": ".".join(str(x) for x in sys.version_info[:3])}
    for name in ("openai", "python-dotenv", "pypdf"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = "not-installed"
    return result


def fingerprint(config: Config, rubric: PDFInput, prompt: str, exam: PDFInput,
                request: dict[str, Any] | None) -> dict[str, Any]:
    result = {"toolkit_version": VERSION, "exam_id": config.raw["exam_id"],
              "config_sha256": config.config_sha256, "manifest_sha256": config.manifest_sha256,
              "rubric_sha256": rubric.sha256, "prompt_sha256": sha256(prompt.encode("utf-8")),
              "exam_sha256": exam.sha256, "exam_filename": exam.path.name,
              "source_code_sha256": code_fingerprint(), "library_versions": library_versions()}
    if request is not None:
        result["request"] = request
    return result


def provenance_path(output: Path) -> Path:
    return output.parent / ".provenance" / output.name


def existing_status(output: Path, config: Config, expected: dict[str, Any]) -> str:
    """Return pending or complete; ambiguity/mismatch is a hard stop, not a regrade."""
    sidecar = provenance_path(output)
    for path in (output, sidecar):
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ExamError(f"Not an ordinary output/provenance file: {path}")
    if not output.exists():
        if sidecar.exists():
            raise ExamError(f"Orphan provenance record: {sidecar}; use a fresh output directory")
        return "pending"
    raw = output.read_bytes()
    validate_result(strict_loads(raw.decode("utf-8-sig")), config)
    if not sidecar.exists():
        raise ExamError(f"{output.name}: no provenance record; not silently reused. Use a fresh --output-dir")
    record = load_json(sidecar)
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ExamError(f"{sidecar}: unsupported provenance record")
    if record.get("result_sha256") != sha256(raw):
        raise ExamError(f"{output.name}: result hash differs from provenance; preserve edits separately")
    actual = record.get("fingerprint")
    if not isinstance(actual, dict):
        raise ExamError(f"{sidecar}: missing input fingerprint")
    for key, value in expected.items():
        if actual.get(key) != value:
            raise ExamError(f"{output.name}: changed {key}; use a fresh --output-dir")
    return "complete"


def upload_pdf(client: Any, pdf: PDFInput, config: Settings) -> str:
    purpose = "assistants" if config.provider == "azure" else "user_data"
    # Send the same inspected bytes, not an unchecked second read of the file.
    result = client.files.create(file=(pdf.path.name, pdf.data, "application/pdf"), purpose=purpose)
    if not isinstance(getattr(result, "id", None), str) or not result.id:
        raise ExamError("Files API returned no usable file ID")
    return result.id


def delete_file(client: Any, identifier: str | None) -> None:
    if identifier:
        try:
            client.files.delete(identifier)
        except Exception as exc:
            print(f"WARNING: uploaded file cleanup failed for {identifier}: {type(exc).__name__}. "
                  "Inspect provider storage and remove it manually.", file=sys.stderr)


def call_model(client: Any, config: Config, options: Settings, prompt: str,
               rubric_id: str, exam_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    def file_part(identifier):
        part = {"type": "input_file", "file_id": identifier}
        if options.pdf_detail:
            part["detail"] = options.pdf_detail
        return part
    request = dict(model=options.deployment, store=False, truncation="disabled",
                   max_output_tokens=options.max_tokens, instructions=prompt,
                   input=[{"role": "user", "content": [file_part(rubric_id), file_part(exam_id),
                           {"type": "input_text", "text": "File 1 is the approved rubric. File 2 is one complete student exam. "
                            "Read every page and grade exactly the manifest items. Return only the required JSON."}]}],
                   text={"format": {"type": "json_schema", "name": "exam_grade", "strict": True,
                                    "schema": output_schema(config)}})
    if options.effort:
        request["reasoning"] = {"effort": options.effort}
    print("  Upload finished; waiting for the scoring response (non-streaming)...", flush=True)
    start = time.monotonic()
    response = client.responses.create(**request)
    status = getattr(response, "status", None)
    if status != "completed":
        raise ExamError(f"Model response status {status!r}; no partial grade saved. "
                        f"Details: {getattr(response, 'incomplete_details', None)}")
    for block in getattr(response, "output", []) or []:
        for content in getattr(block, "content", []) or []:
            if getattr(content, "type", None) == "refusal":
                raise ExamError("Model refused; no grade saved")
    raw = getattr(response, "output_text", None)
    if not isinstance(raw, str) or not raw.strip():
        raise ExamError("Model returned no grade JSON")
    result = validate_result(strict_loads(raw), config)
    usage = getattr(response, "usage", None)
    meta = {"response_id": getattr(response, "id", None), "reported_model": getattr(response, "model", None),
            "elapsed_seconds": round(time.monotonic() - start, 3),
            "input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)}
    print(f"  Response received after {meta['elapsed_seconds']} s; {meta['response_id']}", flush=True)
    return result, meta


def save_result(output: Path, result: dict[str, Any], expected: dict[str, Any], meta: dict[str, Any]) -> None:
    raw = json_bytes(result)
    record = {"schema_version": 1, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "fingerprint": expected, "result_sha256": sha256(raw), "response": meta}
    # Two individually atomic files, not a transactional database. Sidecar is
    # the commit marker. Interruption between files is detected on the next run.
    write_new(output, raw)
    write_new(provenance_path(output), json_bytes(record))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=Path("exam_config.json"))
    p.add_argument("--check", action="store_true", help="No API calls, credentials or writes; model settings are not compared")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--exam", help="Exact PDF filename, including extension")
    group.add_argument("--student", help="Exact id group, preserving leading zeros")
    p.add_argument("--output-dir", type=Path, help="Override evals directory; relative to shell cwd")
    p.add_argument("--version", action="version", version=VERSION)
    args = p.parse_args(argv)
    if args.exam is not None and (Path(args.exam).name != args.exam or not args.exam.lower().endswith(".pdf")):
        p.error("--exam must be one PDF filename, not a path")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    rubric = validate_rubric(config)
    prompt = config.file("prompt").read_text(encoding="utf-8-sig")
    if prompt != generated_prompt(config):
        raise ExamError("Prompt is stale or edited. Update the template/manifest/notes, then run prepare_exam.py --overwrite")
    exams = discover(config, config.file("exams"), ".pdf")
    if args.exam:
        exams = [p for p in exams if p.name == args.exam]
    elif args.student:
        exams = [p for p in exams if config.identity(p.stem)[0] == args.student]
    if not exams:
        raise ExamError("No matching unambiguous exam PDFs")
    destination = args.output_dir.resolve() if args.output_dir else config.file("evals")
    if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
        raise ExamError("Output directory is not an ordinary directory")
    if not args.check and not config.raw["approved_for_scoring"]:
        raise ExamError("Live scoring blocked: approved_for_scoring is false. Complete the human approval checklist first")
    options = None if args.check else settings(config.root)
    request_record = options.public_record() if options else None
    print(f"{VERSION}: {config.raw['exam_id']}, {len(config.items)} criteria, {config.total} points")
    print(f"Input: {config.file('exams')}; output: {destination}")
    snapshots, pending, errors = {}, [], []
    for path in exams:
        try:
            exam = read_pdf(path, byte_limit=config.raw["max_combined_pdf_bytes"])
            check_pair(exam, rubric, config)
            expected = fingerprint(config, rubric, prompt, exam, request_record)
            snapshots[path.name] = expected
            status = existing_status(destination / (path.stem + ".json"), config, expected)
            print(f"  {path.name}: {status}; {exam.page_count} pages; simple-scan bounds checked on {exam.simple_scan_pages}")
            if status == "pending":
                pending.append(path)
        except (ExamError, OSError) as exc:
            errors.append(str(exc))
    if errors:
        raise ExamError("Preflight failed before any API calls:\n  - " + "\n  - ".join(errors))
    if args.check:
        print("Local check passed. No credentials read or API calls made; current provider/model settings were not compared.")
        print("Passing does not establish scan legibility, identity or grading correctness.")
        return 0
    if not pending:
        print("All selected results are valid with matching recorded provenance. Review-flagged results are still complete.")
        return 0
    try:
        from openai import OpenAI
        import fcntl
    except ImportError as exc:
        raise ExamError("Live scoring needs openai and macOS/Linux fcntl; install requirements.txt") from exc
    destination.mkdir(parents=True, exist_ok=True)
    (destination / ".locks").mkdir(exist_ok=True)
    print(f"Provider: {options.provider}; deployment: {options.deployment}; reasoning: {options.effort or 'omitted'}; output cap: {options.max_tokens}")
    failures = 0
    client = OpenAI(api_key=options.api_key, base_url=options.endpoint, timeout=options.timeout, max_retries=options.retries)
    rubric_id = None
    with client:
        try:
            for n, path in enumerate(pending, 1):
                output = destination / (path.stem + ".json")
                lock_path = destination / ".locks" / (path.stem + ".lock")
                if lock_path.is_symlink():
                    raise ExamError("Refusing symlink lock file")
                with lock_path.open("a+") as lock:
                    try:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        print(f"Skip {path.name}: another worker holds the lock")
                        continue
                    try:
                        exam = read_pdf(path, byte_limit=config.raw["max_combined_pdf_bytes"])
                        if exam.sha256 != snapshots[path.name]["exam_sha256"]:
                            raise ExamError(f"{path.name} changed after preflight; do not edit inputs during a run")
                        expected = snapshots[path.name]
                        if existing_status(output, config, expected) == "complete":
                            print(f"Skip {path.name}: another worker completed it")
                            continue
                        print(f"[{n}/{len(pending)}] Grade {path.name}", flush=True)
                        if rubric_id is None:
                            print(f"  Uploading rubric ({rubric.page_count} pages)", flush=True)
                            rubric_id = upload_pdf(client, rubric, options)
                        exam_id = None
                        try:
                            print(f"  Uploading student PDF ({exam.page_count} pages)", flush=True)
                            exam_id = upload_pdf(client, exam, options)
                            result, meta = call_model(client, config, options, prompt, rubric_id, exam_id)
                        finally:
                            delete_file(client, exam_id)
                        save_result(output, result, expected, meta)
                        print(f"  Wrote {output}", flush=True)
                        if result["human_review_recommended"]:
                            print("  HUMAN REVIEW: " + result["human_review_reason"], flush=True)
                    except KeyboardInterrupt:
                        raise
                    except Exception as exc:
                        failures += 1
                        # Do not log raw HTTP requests/headers or credentials.
                        print(f"FAILED {path.name}: {type(exc).__name__}: {str(exc).replace(options.api_key, '[REDACTED]')}", file=sys.stderr)
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        finally:
            delete_file(client, rubric_id)
    print(f"Finished. Failures: {failures}. Original PDFs and previous scores unchanged.")
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExamError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("Interrupted. Completed results remain; inspect any interrupted result/provenance pair.", file=sys.stderr)
        raise SystemExit(130)
