#!/usr/bin/env python3
"""
Variant B: corrected baseline + reason-then-answer, one question per call.

Changes vs. the original script
  * Streaming (SSE) responses, so the gateway never sees an idle connection (main 504 fix).
  * One question per request, max_tokens cap, retries on 408/429/502/503/504 + network errors,
    exponential backoff with jitter.
  * Free-form reasoning first, then a final line `FINAL: <letter>`. No JSON during reasoning.
  * Answer is extracted by regex (with a cheap second-call fallback) and mapped back to the
    option text by the harness, so there are no "reworded option" grading failures.
  * Works for list-shaped exams and dict-shaped exams.
  * A failed/unparseable question never kills the exam; it shows up as FAILED / NO_ANSWER.
  * Per-question disk cache, so a rerun resumes instead of redoing everything.
  * Optional concurrency (--workers).
  * Reports accuracy if the exam JSON contains the correct answer, split by "needs figure".
  * Output is stored per variant + model, so variants never overwrite each other.
  * PDF text is XML-escaped (the original crashed ReportLab on "<" / "&" in answers).

Variants C and E import this file, so keep all three in the same directory.

ASSUMED EXAM FORMAT (adapt `normalize_question` if yours differs):
  {"examId": "...", "questions": [{"id": "q1", "question": "...", "options": ["...", ...]}, ...]}
or a bare list of such questions. Option lists may be strings or dicts with a "text" key.
If a question has a key like "correct" / "correctAnswer" / "answer", it is NEVER sent to the model;
it is only used afterwards to compute accuracy (int = 0-based index, letter, or option text).
"""
import argparse
import glob
import hashlib
import http.client
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Table, TableStyle

API_URL = os.environ.get("SWISSAI_API_URL", "https://api.swissai.svc.cscs.ch/v1/chat/completions")
DEFAULT_MODEL = "CSCS-Inference/swiss-ai/Apertus-v1.5-70B"
RETRY_CODES = {408, 429, 502, 503, 504}
LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GOLD_KEYS = ("correct", "correctAnswer", "correct_answer", "correctOption", "solution", "answer")
CONTEXT_KEYS = ("context", "passage", "given", "preamble")

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
FINAL_LETTER_RE = re.compile(r"(?i:final)\s*(?:answer)?\s*:\s*[*\s]*\(?([A-Z])\)?(?![A-Za-z])")
FINAL_TEXT_RE = re.compile(r"(?i:final)\s*(?:answer)?\s*:\s*(.+)")
FIGURE_RE = re.compile(r"\b(figure|fig\.|diagram|shown (?:above|below)|graph shown|plot shown)\b", re.I)

SYSTEM_B = (
    "You are an expert in Signals and Systems solving exam questions. "
    "Think step by step, carefully and concisely (do not repeat yourself), "
    "then finish with a final line of exactly the form `FINAL: <letter>`."
)


class LLMError(Exception):
    pass


class EmptyResponse(Exception):
    pass


# --------------------------------------------------------------------------- LLM transport
def _stream_once(req, idle_timeout, total_timeout):
    deadline = time.time() + total_timeout
    with urllib.request.urlopen(req, timeout=idle_timeout) as r:  # timeout = idle (per-read) timeout
        ctype = r.headers.get("Content-Type", "")
        if "event-stream" not in ctype:  # server ignored stream=True
            data = json.loads(r.read().decode("utf-8"))
            text = data["choices"][0]["message"]["content"] or ""
        else:
            parts = []
            for raw in r:
                if time.time() > deadline:
                    raise TimeoutError("total generation time exceeded")
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    obj = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("error"):
                    raise http.client.HTTPException(f"stream error: {obj['error']}")
                choices = obj.get("choices") or []
                if not choices:
                    continue
                content = (choices[0].get("delta") or {}).get("content")
                if content:
                    parts.append(content)
            text = "".join(parts)
    text = THINK_RE.sub("", text).strip()
    if not text:
        raise EmptyResponse("empty completion")
    return text


def call_llm(messages, model, api_key, temperature=0.1, max_tokens=3072,
             idle_timeout=120, total_timeout=600, max_attempts=6):
    """Streaming chat completion with retry/backoff. Returns the full text."""
    body = json.dumps({
        "model": model, "messages": messages, "temperature": temperature,
        "max_tokens": max_tokens, "stream": True,
    }).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }
    last_err = None
    for attempt in range(max_attempts):
        req = urllib.request.Request(API_URL, data=body, headers=headers, method="POST")
        try:
            return _stream_once(req, idle_timeout, total_timeout)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                detail = ""
            last_err = f"HTTP {e.code} {e.reason} {detail}"
            if e.code not in RETRY_CODES:
                raise LLMError(last_err) from e
        except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError,
                http.client.HTTPException, EmptyResponse) as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_attempts - 1:
            delay = min(60, 5 * 2 ** attempt) * random.uniform(0.5, 1.0)
            print(f"  [retry {attempt + 1}/{max_attempts - 1} in {delay:.0f}s] {last_err}", flush=True)
            time.sleep(delay)
    raise LLMError(f"gave up after {max_attempts} attempts: {last_err}")


# --------------------------------------------------------------------------- question handling
def load_questions(exam_data):
    if isinstance(exam_data, list):
        return exam_data
    return exam_data.get("questions", [])


def _opt_text(o):
    if isinstance(o, dict):
        for k in ("text", "label", "value", "option"):
            if k in o:
                return str(o[k])
        return json.dumps(o)
    return str(o)


def normalize_question(q, idx):
    """Adapt this function if your exam JSON uses different key names."""
    if not isinstance(q, dict):
        q = {"question": str(q)}
    qid = str(q.get("id") or q.get("qid") or f"q{idx + 1}")
    text = next((str(q[k]) for k in ("question", "text", "prompt", "stem") if q.get(k)), "")
    opts_raw = next((q[k] for k in ("options", "choices", "answers") if isinstance(q.get(k), (list, tuple))), [])
    if isinstance(q.get("options"), dict):
        opts_raw = [q["options"][k] for k in sorted(q["options"])]
    options = [_opt_text(o) for o in opts_raw]
    context = "\n".join(str(q[k]) for k in CONTEXT_KEYS if isinstance(q.get(k), str))
    fig_keys = any(q.get(k) for k in ("image", "images", "figure", "diagram", "img"))
    needs_figure = bool(fig_keys or FIGURE_RE.search(text + " " + context))
    return {"id": qid, "text": text, "context": context, "options": options,
            "needs_figure": needs_figure, "raw": q}


def gold_choice(nq):
    """Letter of the gold answer if the exam file contains one, else None."""
    raw, opts = nq["raw"], nq["options"]
    for k in GOLD_KEYS:
        if k in raw:
            g = raw[k]
            break
    else:
        return None
    if isinstance(g, bool):
        return None
    if isinstance(g, int):  # NOTE: assumes 0-based. Change to g - 1 if your data is 1-based.
        return LETTERS[g] if 0 <= g < len(opts) else None
    if isinstance(g, str):
        s = g.strip()
        if len(s) == 1 and s.upper() in LETTERS[:len(opts)]:
            return s.upper()
        for i, o in enumerate(opts):
            if o.strip().lower() == s.lower():
                return LETTERS[i]
    return None


def question_block(nq):
    parts = []
    if nq["context"]:
        parts.append(f"Context:\n{nq['context']}\n")
    parts.append(f"Question:\n{nq['text']}")
    if nq["options"]:
        parts.append("Options:\n" + "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(nq["options"])))
    return "\n\n".join(parts)


def build_messages(nq, system=SYSTEM_B):
    if nq["options"]:
        tail = "Reason step by step, then end with a line `FINAL: <letter>` (e.g. `FINAL: B`)."
    else:
        tail = "Reason step by step, then end with a line `FINAL: <your final answer>`."
    return [{"role": "system", "content": system},
            {"role": "user", "content": question_block(nq) + "\n\n" + tail}]


# --------------------------------------------------------------------------- answer extraction
def parse_final(text, nq):
    """Return the chosen letter (MC) or answer text (open); None if not found."""
    if nq["options"]:
        for m in reversed(FINAL_LETTER_RE.findall(text)):
            if LETTERS.find(m) != -1 and LETTERS.index(m) < len(nq["options"]):
                return m
        return None
    ms = FINAL_TEXT_RE.findall(text)
    return ms[-1].strip().strip("*").strip() if ms else None


def fallback_extract(reasoning, nq, args, api_key):
    """Cheap second call used when the regex finds no FINAL line (e.g. output was cut off)."""
    n = len(nq["options"])
    ask = ("Reply with ONLY the letter of the option this solution concludes with. "
           "If it never reaches a conclusion, solve the problem yourself and reply with your best letter."
           if n else "Reply with ONLY the final answer this solution concludes with.")
    msgs = [{"role": "user", "content": question_block(nq) + "\n\nWorked solution so far:\n"
             + reasoning[-6000:] + "\n\n" + ask}]
    try:
        out = call_llm(msgs, args.model, api_key, temperature=0.0, max_tokens=64 if not n else 16,
                       idle_timeout=args.idle_timeout, max_attempts=3)
    except (LLMError, EmptyResponse):
        return None
    if n:
        for m in re.findall(r"\b([A-Z])\b", out):
            if LETTERS.index(m) < n:
                return m
        return None
    return out.strip() or None


def sample_once(nq, args, api_key, temperature=None, messages=None):
    """One reasoning sample. Returns {"choice", "reasoning", "fallback"}."""
    text = call_llm(messages or build_messages(nq), args.model, api_key,
                    temperature=args.temperature if temperature is None else temperature,
                    max_tokens=args.max_tokens, idle_timeout=args.idle_timeout)
    choice = parse_final(text, nq)
    fb = False
    if choice is None:
        choice, fb = fallback_extract(text, nq, args, api_key), True
    return {"choice": choice, "reasoning": text, "fallback": fb}


def make_result(nq, choice, reasoning, **extra):
    if choice is None:
        answer, status = "NO_ANSWER", "NO_ANSWER"
    else:
        answer = nq["options"][LETTERS.index(choice)] if nq["options"] else choice
        status = "OK"
    res = {"id": nq["id"], "question": nq["text"][:300], "choice": choice, "answer": answer,
           "explanation": reasoning, "status": status, "needs_figure": nq["needs_figure"]}
    res.update(extra)
    return res


# --------------------------------------------------------------------------- default solver (variant B)
def solve_question_b(nq, args, api_key):
    s = sample_once(nq, args, api_key)
    return make_result(nq, s["choice"], s["reasoning"], used_fallback=s["fallback"])


# --------------------------------------------------------------------------- exam runner
def _slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def _score(results, norm_by_id):
    graded = correct = 0
    g_text = c_text = 0
    for r in results:
        g = gold_choice(norm_by_id[r["id"]])
        if g is None:
            continue
        ok = (r.get("choice") == g)
        r["correct"] = ok
        graded += 1
        correct += ok
        if not r.get("needs_figure"):
            g_text += 1
            c_text += ok
    return {
        "questions": len(results),
        "ok": sum(r["status"] == "OK" for r in results),
        "no_answer": sum(r["status"] == "NO_ANSWER" for r in results),
        "failed": sum(r["status"] == "FAILED" for r in results),
        "graded": graded, "correct": correct,
        "accuracy": round(correct / graded, 4) if graded else None,
        "accuracy_text_only": round(c_text / g_text, 4) if g_text else None,
        "needs_figure": sum(1 for r in results if r.get("needs_figure")),
    }


def run_exam(exam_dir, exam_id, args, api_key, solver, variant):
    exam_file = os.path.join(args.data_root, exam_dir, f"exam_{exam_id}.json")
    out_dir = os.path.join(args.out_root, exam_dir, variant, _slug(args.model))
    cache_dir = os.path.join(out_dir, "cache", exam_id)
    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False
    print(f"\n--- Exam {exam_id} ({exam_dir}) | variant {variant} | {args.model} ---", flush=True)
    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)
    norm = [normalize_question(q, i) for i, q in enumerate(load_questions(exam_data))]
    norm_by_id = {n["id"]: n for n in norm}
    exam_label = exam_data.get("examId", exam_id) if isinstance(exam_data, dict) else exam_id
    os.makedirs(cache_dir, exist_ok=True)
    done = [0]

    def work(nq):
        qhash = hashlib.sha1(json.dumps([nq["text"], nq["context"], nq["options"]]).encode()).hexdigest()[:12]
        cpath = os.path.join(cache_dir, _slug(nq["id"]) + ".json")
        if not args.no_cache and os.path.exists(cpath):
            try:
                with open(cpath, "r", encoding="utf-8") as f:
                    c = json.load(f)
                if c.get("qhash") == qhash:
                    res = c["result"]
                    res["cached"] = True
                    return res
            except Exception:
                pass
        try:
            res = solver(nq, args, api_key)
        except Exception as e:  # never let one question kill the exam
            res = {"id": nq["id"], "question": nq["text"][:300], "choice": None, "answer": "FAILED",
                   "explanation": f"ERROR: {type(e).__name__}: {e}", "status": "FAILED",
                   "needs_figure": nq["needs_figure"]}
        if res["status"] == "OK":
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump({"qhash": qhash, "result": res}, f)
        done[0] += 1
        print(f"  [{done[0]}/{len(norm)}] {nq['id']}: {res['status']} {res.get('choice')}", flush=True)
        return res

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        results = list(ex.map(work, norm))

    summary = _score(results, norm_by_id)
    solution = {"examId": exam_label, "examTitle": "Signals & Systems Solutions", "variant": variant,
                "model": args.model, "summary": summary, "answers": results}
    os.makedirs(out_dir, exist_ok=True)
    out_json = os.path.join(out_dir, f"solutions_{exam_id}.json")
    out_pdf = os.path.join(out_dir, f"output_{exam_id}.pdf")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(solution, f, indent=2, ensure_ascii=False)
    print(f"Summary: {json.dumps(summary)}")
    print(f"JSON -> {out_json}")
    try:
        generate_compact_pdf(solution, out_pdf, exam_id)
        print(f"PDF  -> {out_pdf}")
    except Exception as e:
        print(f"Warning: PDF generation failed ({e}); JSON is still saved.")
    return True


# --------------------------------------------------------------------------- PDF
def _p(text, style, limit=None):
    text = str(text)
    if limit and len(text) > limit:
        text = text[:limit] + " ..."
    return Paragraph(escape_xml(text).replace("\n", "<br/>"), style)


def escape_xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_compact_pdf(sol, path, exam_id):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=18)
    ss = getSampleStyleSheet()
    mk = lambda name, parent, font, size, lead, col: ParagraphStyle(
        name, parent=ss[parent], fontName=font, fontSize=size, leading=lead, textColor=colors.HexColor(col))
    title = mk("DocTitle", "Heading1", "Helvetica-Bold", 12, 14, "#1A2B4C")
    qid = mk("QID", "Normal", "Helvetica-Bold", 8, 10, "#1A2B4C")
    txt = mk("QText", "Normal", "Helvetica", 8, 10, "#222222")
    ans = mk("QAns", "Normal", "Helvetica-Bold", 8, 10, "#0D6EFD")
    expl = mk("QExpl", "Normal", "Helvetica-Oblique", 7.5, 9.5, "#333333")

    s = sol.get("summary", {})
    acc = f" | accuracy {s['accuracy']:.1%} ({s['correct']}/{s['graded']})" if s.get("accuracy") is not None else ""
    story = [_p(f"{sol.get('examTitle', 'Exam Solutions')} - {str(sol.get('examId', exam_id)).upper()} "
                f"[variant {sol.get('variant', '?')}]{acc}", title),
             HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1A2B4C"), spaceBefore=2, spaceAfter=4)]
    rows = [[_p("Q#", qid), _p("Question / Context", qid), _p("Selected Answer", qid), _p("Solution Logic", qid)]]
    for i, it in enumerate(sol.get("answers", [])):
        mark = {True: " [OK]", False: " [X]"}.get(it.get("correct"), "")
        fig = " (fig)" if it.get("needs_figure") else ""
        prefix = f"{it['choice']}. " if it.get("choice") else ""
        rows.append([_p(f"{it.get('id', f'Q{i + 1}')}{mark}{fig}", qid),
                     _p(it.get("question", "-"), txt, 400),
                     _p(prefix + str(it.get("answer", "-")), ans, 300),
                     _p(it.get("explanation", "-"), expl, 1200)])
    t = Table(rows, colWidths=[45, 180, 130, 221], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F0F4F8")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D0D7DE")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")])]))
    story.append(t)
    doc.build(story)


# --------------------------------------------------------------------------- CLI
def build_parser(description, add_args=None):
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--examdir", default="signals-and-systems", help="Directory under data/ with exam JSON files.")
    p.add_argument("--examid", default=None, help="Specific exam ID (e.g. hs17). Omit to run all exams in the directory.")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--workers", type=int, default=3, help="Concurrent questions.")
    p.add_argument("--max-tokens", type=int, default=3072)
    p.add_argument("--temperature", type=float, default=0.1)
    p.add_argument("--idle-timeout", type=int, default=120, help="Seconds without any streamed bytes before giving up.")
    p.add_argument("--no-cache", action="store_true", help="Ignore cached per-question results.")
    p.add_argument("--data-root", default="data")
    p.add_argument("--out-root", default="llm_output")
    if add_args:
        add_args(p)
    return p


def run_cli(solver, variant, add_args=None, argv=None, description="Exam solving harness."):
    """`variant` is a string or a callable(args) -> string (used for output/cache folder names)."""
    try:
        args = build_parser(description, add_args).parse_args(argv)
        variant_name = variant(args) if callable(variant) else variant
        api_key = os.environ.get("SWISSAI_RESEARCH_API_KEY")
        if not api_key:
            print("Error: SWISSAI_RESEARCH_API_KEY is not set.")
            return 1
        target = os.path.join(args.data_root, args.examdir)
        if not os.path.isdir(target):
            print(f"Error: directory '{target}' does not exist.")
            return 1
        if args.examid:
            return 0 if run_exam(args.examdir, args.examid, args, api_key, solver, variant_name) else 1
        files = sorted(glob.glob(os.path.join(target, "exam_*.json")))
        if not files:
            print(f"No exam_*.json files in '{target}'.")
            return 1
        ok = 0
        for fp in files:
            m = re.match(r"exam_(.+)\.json", os.path.basename(fp))
            if m and run_exam(args.examdir, m.group(1), args, api_key, solver, variant_name):
                ok += 1
        print(f"\nBatch complete: {ok}/{len(files)} exams processed.")
        return 0 if ok else 1
    except KeyboardInterrupt:
        print("\nInterrupted. Per-question results already finished are cached; rerun to resume.")
        return 130


if __name__ == "__main__":
    sys.exit(run_cli(solve_question_b, "B", description="Variant B: reason-then-answer, 1 question/call."))