"""Shared, provider-independent exam configuration and validation.

Nothing in this module makes network calls or reads credentials. The ordered
manifest is loaded once by each command; there is no exam-specific item list in
Python. See docs/FORMATS.md before changing the output contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable

VERSION = "EXAM_TOOLKIT_1.0.0"
GRADE_FIELDS = ("rubric_item", "rubric_name", "max_points", "awarded_points", "explanation")
RESULT_FIELDS = ("grades", "human_review_recommended", "human_review_reason")


class ExamError(ValueError):
    """An input, configuration or output fails a documented safety check."""


def strict_loads(text: str, *, decimals: bool = False) -> Any:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ExamError(f"Duplicate JSON key: {key}")
            obj[key] = value
        return obj

    def invalid(value):
        raise ExamError(f"Nonstandard JSON constant: {value}")

    kwargs = {"object_pairs_hook": unique, "parse_constant": invalid}
    if decimals:
        kwargs.update(parse_float=Decimal, parse_int=Decimal)
    try:
        return json.loads(text, **kwargs)
    except (ValueError, RecursionError) as exc:
        raise ExamError(f"Invalid JSON: {exc}") from exc


def load_json(path: Path) -> Any:
    return strict_loads(path.read_text(encoding="utf-8-sig"))


def number(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ExamError(f"{label}: expected a number, not {value!r}")
    try:
        d = Decimal(str(value))
        f = float(d)
    except (ValueError, OverflowError) as exc:
        raise ExamError(f"{label}: invalid number") from exc
    if not d.is_finite() or not math.isfinite(f) or (d != 0 and f == 0):
        raise ExamError(f"{label}: expected a finite representable number")
    # A practical bound prevents pathological decimal exponents in local sums.
    if len(d.as_tuple().digits) > 100 or abs(d.as_tuple().exponent) > 300:
        raise ExamError(f"{label}: unreasonable numeric precision")
    return d


def exact_sum(values: Iterable[Decimal]) -> Decimal:
    values = list(values)
    with localcontext() as ctx:
        ctx.prec = max([40] + [len(x.as_tuple().digits) + abs(x.as_tuple().exponent) + 12 for x in values])
        return sum(values, Decimal(0))


def numeric(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def text(value: Any, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise ExamError(f"{label}: expected a {'possibly empty' if empty else 'nonempty'} string")
    if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value):
        raise ExamError(f"{label}: unexpected control character")
    return value


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("ascii")


def write_new(path: Path, data: bytes) -> None:
    """Atomic no-overwrite publication on a local macOS/Linux filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp, path)  # Fail rather than replace any existing file/symlink.
    finally:
        tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class Item:
    label: str
    name: str
    maximum: Decimal
    part: str
    problem: str
    mode: str
    allowed: tuple[Decimal, ...]
    step: Decimal | None
    notes: str
    dependencies: tuple[str, ...]
    correct_option: str | None
    correct_answer: str | None

    def record(self) -> dict[str, Any]:
        return {"rubric_item": self.label, "rubric_name": self.name,
                "max_points": numeric(self.maximum)}

    def policy_record(self) -> dict[str, Any]:
        d = self.record()
        d.update(part_id=self.part, problem_id=self.problem, score_mode=self.mode,
                 notes=self.notes, dependencies=list(self.dependencies))
        if self.mode == "allowed":
            d["allowed_points"] = [numeric(x) for x in self.allowed]
        elif self.mode == "step":
            d["score_step"] = numeric(self.step)
        if self.correct_option is not None:
            d.update(correct_option=self.correct_option, correct_answer=self.correct_answer)
        return d

    def validate_score(self, value: Any) -> Decimal:
        d = number(value, f"{self.label}.awarded_points")
        if not 0 <= d <= self.maximum:
            raise ExamError(f"{self.label}: score {d} outside 0..{self.maximum}")
        if self.mode == "allowed" and d not in self.allowed:
            raise ExamError(f"{self.label}: score {d} not in {self.allowed}")
        if self.mode == "step":
            with localcontext() as ctx:
                ctx.prec = 400
                if d % self.step != 0:
                    raise ExamError(f"{self.label}: score {d} is not a multiple of {self.step}")
        return d


@dataclass(frozen=True)
class Config:
    path: Path
    raw: dict[str, Any]
    manifest: dict[str, Any]
    items: tuple[Item, ...]
    config_sha256: str
    manifest_sha256: str

    @property
    def root(self) -> Path:
        return self.path.parent

    def file(self, key: str) -> Path:
        return (self.root / self.raw["paths"][key]).resolve()

    @property
    def total(self) -> Decimal:
        return exact_sum(i.maximum for i in self.items)

    @property
    def pattern(self):
        return re.compile(self.raw["filename_pattern"], re.IGNORECASE)

    def identity(self, stem: str) -> tuple[str, Any]:
        m = self.pattern.fullmatch(stem)
        if m is None or not m.group("id"):
            raise ExamError(f"Filename stem {stem!r} does not match filename_pattern")
        identifier = m.group("id")
        if self.raw["identity_mode"] == "numeric":
            if re.fullmatch(r"[0-9]+", identifier) is None:
                raise ExamError("Numeric identity_mode requires decimal digits in the id group")
            key = int(identifier)
        else:
            key = identifier.casefold()
        return identifier, key


def load_config(path: Path) -> Config:
    path = path.resolve()
    raw_bytes = path.read_bytes()
    raw = strict_loads(raw_bytes.decode("utf-8-sig"))
    expected = {"schema_version", "exam_id", "exam_title", "approved_for_scoring", "paths",
                "filename_pattern", "identity_mode", "max_combined_pdf_bytes", "rubric_validation", "notes"}
    if not isinstance(raw, dict) or set(raw) != expected:
        raise ExamError(f"{path}: expected keys {sorted(expected)}; unknown keys are not silently ignored")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise ExamError("Unsupported config schema_version")
    for key in ("exam_id", "exam_title", "filename_pattern"):
        text(raw[key], key)
    text(raw["notes"], "notes", empty=True)
    if type(raw["approved_for_scoring"]) is not bool:
        raise ExamError("approved_for_scoring must be a boolean")
    if raw["identity_mode"] not in ("numeric", "text"):
        raise ExamError("identity_mode must be numeric or text")
    try:
        pattern = re.compile(raw["filename_pattern"], re.IGNORECASE)
    except re.error as exc:
        raise ExamError(f"Invalid filename_pattern: {exc}") from exc
    if set(pattern.groupindex) != {"id"}:
        raise ExamError("filename_pattern must contain one named group (?P<id>...)")
    paths = raw["paths"]
    path_keys = {"manifest", "rubric", "prompt_template", "prompt", "exams", "evals"}
    if not isinstance(paths, dict) or set(paths) != path_keys:
        raise ExamError(f"paths must contain {sorted(path_keys)}")
    for key, value in paths.items():
        text(value, f"paths.{key}")
        p = Path(value)
        if p.is_absolute() or ".." in p.parts:
            raise ExamError(f"paths.{key} must be a project-relative path without '..'")
    resolved = [(path.parent / x).resolve() for x in paths.values()]
    if any(not x.is_relative_to(path.parent) for x in resolved):
        raise ExamError("Configured paths cannot escape the project root through symlinks")
    if len(set(resolved)) != len(resolved):
        raise ExamError("Configured paths must be distinct")
    if type(raw["max_combined_pdf_bytes"]) is not int or not 0 < raw["max_combined_pdf_bytes"] <= 50_000_000:
        raise ExamError("max_combined_pdf_bytes must be in 1..50000000; this toolkit does not raise the provider limit")
    rv = raw["rubric_validation"]
    if not isinstance(rv, dict) or set(rv) != {"mode", "approved_sha256"} or rv["mode"] not in ("headings", "sha256"):
        raise ExamError("rubric_validation must specify mode headings or sha256, and approved_sha256")
    if rv["mode"] == "sha256" and (not isinstance(rv["approved_sha256"], str) or re.fullmatch(r"[0-9a-f]{64}", rv["approved_sha256"]) is None):
        raise ExamError("sha256 mode needs a manually reviewed PDF's 64-character approved_sha256")
    if rv["mode"] == "headings" and rv["approved_sha256"] != "":
        raise ExamError("In headings mode leave approved_sha256 empty")
    mf_bytes = (path.parent / paths["manifest"]).read_bytes()
    manifest = strict_loads(mf_bytes.decode("utf-8-sig"))
    if not isinstance(manifest, dict) or set(manifest) != {"exam_id", "expected_total_max_points", "items"}:
        raise ExamError("Manifest needs exam_id, expected_total_max_points, items")
    if manifest["exam_id"] != raw["exam_id"]:
        raise ExamError("Config and manifest exam_id differ")
    if not isinstance(manifest["items"], list) or not manifest["items"]:
        raise ExamError("Manifest items must be a nonempty array")
    items = []
    for rec in manifest["items"]:
        required = {"rubric_item", "rubric_name", "max_points", "part_id", "problem_id", "score_mode", "notes", "dependencies"}
        optional = {"allowed_points", "score_step", "correct_option", "correct_answer"}
        if not isinstance(rec, dict) or not required <= set(rec) or set(rec) - required - optional:
            raise ExamError(f"Invalid manifest item fields: {rec!r}")
        for key in ("rubric_item", "rubric_name", "part_id", "problem_id"):
            text(rec[key], key)
        for key in ("rubric_item", "part_id", "problem_id"):
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.()-]*", rec[key]) is None:
                raise ExamError(f"{key}: use stable ASCII letters/digits and . _ ( ) -")
        maximum = number(rec["max_points"], "max_points")
        if maximum <= 0:
            raise ExamError("Scored items must have positive maxima; exclude external items explicitly")
        mode = rec["score_mode"]
        if mode not in ("allowed", "step", "continuous"):
            raise ExamError("score_mode must be allowed, step or continuous")
        allowed, step = (), None
        if mode == "allowed":
            if not isinstance(rec.get("allowed_points"), list) or "score_step" in rec:
                raise ExamError("allowed mode requires allowed_points and no score_step")
            allowed = tuple(number(v, "allowed_points") for v in rec["allowed_points"])
            if tuple(sorted(set(allowed))) != allowed or not allowed or allowed[0] != 0 or allowed[-1] != maximum:
                raise ExamError("allowed_points must be ascending, unique, start at zero and end at max_points")
        elif mode == "step":
            step = number(rec.get("score_step"), "score_step")
            if step <= 0 or "allowed_points" in rec:
                raise ExamError("step mode requires positive score_step and no allowed_points")
            with localcontext() as ctx:
                ctx.prec = 400
                if maximum % step != 0:
                    raise ExamError("max_points must be a multiple of score_step")
        elif "allowed_points" in rec or "score_step" in rec:
            raise ExamError("continuous mode has neither allowed_points nor score_step")
        deps = rec["dependencies"]
        if not isinstance(deps, list) or any(not isinstance(x, str) for x in deps) or len(set(deps)) != len(deps):
            raise ExamError("dependencies must be a list of distinct criterion identifiers")
        notes = text(rec["notes"], "item.notes", empty=True)
        option, answer = rec.get("correct_option"), rec.get("correct_answer")
        if ("correct_option" in rec) != ("correct_answer" in rec):
            raise ExamError("Supply correct_option and correct_answer together")
        if "correct_option" in rec:
            text(option, "correct_option")
            text(answer, "correct_answer")
        items.append(Item(rec["rubric_item"], rec["rubric_name"], maximum, rec["part_id"],
                          rec["problem_id"], mode, allowed, step, notes, tuple(deps), option, answer))
    by_id = {i.label: i for i in items}
    if len(by_id) != len(items):
        raise ExamError("Duplicate rubric_item in manifest")
    for kind, labels in (("item", [i.label for i in items]), ("part", list(dict.fromkeys(i.part for i in items))),
                         ("problem", list(dict.fromkeys(i.problem for i in items)))):
        if len({label.casefold() for label in labels}) != len(labels):
            raise ExamError(f"{kind} identifiers must also be unique ignoring case (review navigation)")
    part_problems = {}
    for item in items:
        if any(d not in by_id or d == item.label for d in item.dependencies):
            raise ExamError(f"{item.label}: unknown or self dependency")
        if item.part in part_problems and part_problems[item.part] != item.problem:
            raise ExamError("A part_id cannot belong to multiple problem_id values")
        part_problems[item.part] = item.problem
    # Dependencies document evidence links; a cycle usually means a configuration error.
    def visit(label, visiting, done):
        if label in visiting:
            raise ExamError("Cyclic manifest dependency")
        if label in done:
            return
        for dep in by_id[label].dependencies:
            visit(dep, visiting | {label}, done)
        done.add(label)
    done = set()
    for label in by_id:
        visit(label, set(), done)
    total = exact_sum(i.maximum for i in items)
    if total != number(manifest["expected_total_max_points"], "expected_total_max_points"):
        raise ExamError(f"Manifest maxima sum to {total}, not the declared total")
    return Config(path, raw, manifest, tuple(items), sha256(raw_bytes), sha256(mf_bytes))


def validate_result(data: Any, config: Config, *, ordered: bool = True) -> dict[str, Any]:
    if not isinstance(data, dict) or set(data) != set(RESULT_FIELDS):
        raise ExamError("Expected exactly grades, human_review_recommended, human_review_reason")
    records = data["grades"]
    if not isinstance(records, list) or len(records) != len(config.items):
        raise ExamError(f"Expected exactly {len(config.items)} grades; missing scores are NOT zero")
    seen = {}
    lookup = {i.label: i for i in config.items}
    for index, record in enumerate(records):
        if not isinstance(record, dict) or set(record) != set(GRADE_FIELDS):
            raise ExamError(f"Grade {index + 1}: wrong fields")
        label = record["rubric_item"]
        if not isinstance(label, str) or label not in lookup or label in seen:
            raise ExamError(f"Unknown/duplicate rubric_item: {label!r}")
        item = lookup[label]
        if ordered and label != config.items[index].label:
            raise ExamError(f"Grade {index + 1}: expected {config.items[index].label}")
        if record["rubric_name"] != item.name or number(record["max_points"], "max_points") != item.maximum:
            raise ExamError(f"{label}: name or maximum differs from manifest")
        item.validate_score(record["awarded_points"])
        text(record["explanation"], f"{label}.explanation")
        seen[label] = record
    review = data["human_review_recommended"]
    reason = text(data["human_review_reason"], "human_review_reason", empty=True)
    if type(review) is not bool or review != bool(reason.strip()):
        raise ExamError("Human-review flag and reason disagree")
    return {"grades": [seen[i.label] for i in config.items],
            "human_review_recommended": review, "human_review_reason": reason}


def output_schema(config: Config) -> dict[str, Any]:
    """Small common JSON schema; local validation enforces each item's exact rules.

    Deliberately avoids per-item unions that hit provider nesting/property limits.
    JSON-schema validity is not evidence of grading correctness.
    """
    grade = {"type": "object", "properties": {
        "rubric_item": {"type": "string"}, "rubric_name": {"type": "string"},
        "max_points": {"type": "number"}, "awarded_points": {"type": "number"},
        "explanation": {"type": "string"}}, "required": list(GRADE_FIELDS), "additionalProperties": False}
    return {"type": "object", "properties": {
        "grades": {"type": "array", "items": grade},
        "human_review_recommended": {"type": "boolean"},
        "human_review_reason": {"type": "string"}},
        "required": list(RESULT_FIELDS), "additionalProperties": False}


def generated_prompt(config: Config) -> str:
    template = config.file("prompt_template").read_text(encoding="utf-8-sig").strip()
    if not template:
        raise ExamError("Prompt template is empty")
    digest = sha256(config.file("rubric").read_bytes())
    contract = {"exam_id": config.raw["exam_id"], "exam_title": config.raw["exam_title"],
                "expected_item_count": len(config.items), "expected_total_max_points": numeric(config.total),
                "rubric_sha256": digest, "exam_notes": config.raw["notes"],
                "items": [i.policy_record() for i in config.items]}
    return (f"EXAM_ID: {config.raw['exam_id']}\n" + template +
            "\n\nEXAM-SPECIFIC MANIFEST AND POLICIES\n" +
            json.dumps(contract, ensure_ascii=True, indent=2) + "\n")


def discover(config: Config, folder: Path, suffix: str) -> list[Path]:
    if not folder.is_dir():
        raise ExamError(f"Missing directory: {folder}")
    groups, errors = {}, []
    for path in sorted(folder.iterdir(), key=lambda p: p.name):
        if path.name.startswith(".") or path.suffix.lower() != suffix:
            continue
        if path.is_symlink() or not path.is_file():
            errors.append(f"Not an ordinary file: {path.name}")
            continue
        try:
            _, key = config.identity(path.stem)
            groups.setdefault(key, []).append(path)
        except ExamError as exc:
            errors.append(str(exc))
    for key, paths in groups.items():
        if len(paths) != 1:
            errors.append(f"Duplicate exam identity {key}: " + ", ".join(p.name for p in paths))
    if errors:
        raise ExamError("Input inventory errors:\n  - " + "\n  - ".join(errors))
    return [groups[key][0] for key in sorted(groups)]
