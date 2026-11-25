"""
TOOL-HARNESS, MC (native tool calling with a sandboxed `run_python` tool)

The model may call `run_python` a limited number of times to compute or verify results
(numpy / scipy / sympy), then must answer with the same JSON as solve_exam_b.py:
    {"reasoning": "...", "answer": "<letter>"}

Outputs
  processed-data/tool-harness/{model_name}/solutions_tools_{exam_id}.json   -> same schema as solve_exam_b.py (id, reasoning, answer)
  processed-data/tool-harness/{model_name}/traces_tools_{exam_id}.json      -> per-question tool trace (code, outputs, turns), for analysis
                                                                               and for a meta-harness proposer to read.

SANDBOX NOTE: execution happens in a subprocess with a timeout, CPU/memory/file-size limits (POSIX), a scrubbed
environment (your API key is NOT passed), a temp working directory and Python-level network blocking. This is
best-effort isolation, not a security boundary. For untrusted settings run the whole script in a container
without network access.
"""
import os
import re
import sys
import json
import time
import socket
import base64
import argparse
import tempfile
import subprocess
import urllib.request
import urllib.error

DEFAULT_ENDPOINT = "https://api.swissai.svc.cscs.ch/v1/chat/completions"

# ----------------------------------------------------------------------------
# Rate limiting (same behaviour as solve_exam_b.py, rate configurable)
# ----------------------------------------------------------------------------
_LAST_API_CALL_TIME = 0.0
MIN_API_INTERVAL = 60.0 / 14.0


def enforce_rate_limit():
    global _LAST_API_CALL_TIME
    elapsed = time.time() - _LAST_API_CALL_TIME
    if elapsed < MIN_API_INTERVAL:
        time.sleep(MIN_API_INTERVAL - elapsed)
    _LAST_API_CALL_TIME = time.time()


# ----------------------------------------------------------------------------
# Images (same as solve_exam_b.py)
# ----------------------------------------------------------------------------
def encode_image_to_base64(image_path):
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")
            ext = image_path.split('.')[-1].lower()
            mime = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/png"
            return f"data:{mime};base64,{encoded}"
    return None


def resolve_and_verify_image_path(exam_dir, img_path):
    if not img_path:
        return None
    if os.path.exists(img_path):
        return img_path
    candidate = os.path.join("data", exam_dir, img_path)
    if os.path.exists(candidate):
        return candidate
    print(f"Warning: Image path specified ('{img_path}') but file does not exist on disk. Proceeding as text-only.")
    return None


# ----------------------------------------------------------------------------
# Output parsing (same as solve_exam_b.py)
# ----------------------------------------------------------------------------
def extract_json_safely(raw_content):
    content = raw_content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise e


def parse_model_output(raw_content):
    """Returns (reasoning, answer). Reasoning: <reasoning> tags -> JSON key -> <think>."""
    think_match = re.search(r'<think>(.*?)</think>', raw_content, re.DOTALL)
    think_text = think_match.group(1).strip() if think_match else None
    content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

    reasoning_match = re.search(r'<reasoning>(.*?)</reasoning>', content, re.DOTALL)
    tag_reasoning = reasoning_match.group(1).strip() if reasoning_match else None

    parsed = None
    try:
        parsed = extract_json_safely(content)
        if not isinstance(parsed, dict):
            parsed = None
    except Exception:
        parsed = None

    answer = None
    if parsed and "answer" in parsed:
        answer = str(parsed["answer"]).strip().upper()
    else:
        ans_match = re.search(r'"answer"\s*:\s*"\s*([A-Oa-o])\s*"', content)
        if ans_match:
            answer = ans_match.group(1).upper()

    reasoning = tag_reasoning
    if not reasoning and parsed and parsed.get("reasoning"):
        reasoning = str(parsed["reasoning"]).strip()
    if not reasoning and think_text:
        reasoning = think_text
    return reasoning or "", answer


# ----------------------------------------------------------------------------
# Sandboxed Python execution
# ----------------------------------------------------------------------------
SANDBOX_PREAMBLE = (
    "import socket as _s, warnings as _w\n"
    "def _no_net(*a, **k): raise RuntimeError('Network access is disabled in this sandbox.')\n"
    "_s.socket = _no_net; _s.create_connection = _no_net; _s.getaddrinfo = _no_net\n"
    "_w.filterwarnings('ignore')\n"
    "del _s, _w\n"
)
PREAMBLE_LINES = SANDBOX_PREAMBLE.count("\n")
MAX_OUTPUT_CHARS = 4000


def _make_preexec(mem_mb, cpu_s):
    def _set_limits():
        try:
            import resource
            mem = mem_mb * 1024 * 1024
            for res, val in ((resource.RLIMIT_AS, mem), (resource.RLIMIT_CPU, cpu_s),
                             (resource.RLIMIT_FSIZE, 10 * 1024 * 1024)):
                try:
                    resource.setrlimit(res, (val, val))
                except (ValueError, OSError):
                    pass  # e.g. RLIMIT_AS is not enforceable on some platforms
        except ImportError:
            pass
    return _set_limits


def run_python(code, timeout=20, mem_mb=2048):
    """Runs `code` in a subprocess. Returns a string (stdout, then stderr tail) truncated for the model."""
    if not isinstance(code, str) or not code.strip():
        return "ERROR: empty or non-string `code` argument."
    with tempfile.TemporaryDirectory(prefix="sandbox_") as td:
        path = os.path.join(td, "snippet.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SANDBOX_PREAMBLE + code)
        env = {"PATH": os.environ.get("PATH", ""), "HOME": td, "TMPDIR": td, "MPLBACKEND": "Agg",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}
        if os.environ.get("SYSTEMROOT"):  # Windows needs this
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
        kwargs = {"preexec_fn": _make_preexec(mem_mb, timeout + 5)} if os.name == "posix" else {}
        try:
            proc = subprocess.run([sys.executable, path], cwd=td, env=env, capture_output=True, text=True,
                                  timeout=timeout, **kwargs)
        except subprocess.TimeoutExpired:
            return f"ERROR: execution timed out after {timeout}s. Use a cheaper computation."
        except Exception as ex:
            return f"ERROR: could not execute code: {ex}"
    out = proc.stdout or ""
    err = (proc.stderr or "").strip()
    if err:
        # Report traceback line numbers relative to the model's own code.
        err = re.sub(r'line (\d+)', lambda m: f"line {max(int(m.group(1)) - PREAMBLE_LINES, 1)}", err)
        out += ("\n" if out else "") + "[stderr]\n" + err[-1500:]
    if not out.strip():
        out = "(no output; use print() to display results)"
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[output truncated]"
    return out


TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_python",
        "description": ("Execute Python 3 code and return what it prints (stdout) plus any error. "
                        "numpy, scipy and sympy are available. No network, no internet, no figure access, "
                        "no state kept between calls. Always print() the values you need."),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Complete, self-contained Python code."}},
            "required": ["code"],
        },
    },
}]


# ----------------------------------------------------------------------------
# Prompt
# ----------------------------------------------------------------------------
def build_prompt(q, options_str, img_path, max_tool_rounds):
    instructions = f"""### Tool use
You have a `run_python` tool (Python 3 with numpy, scipy, sympy). Use it when it helps you compute or verify a result: numerical evaluation, symbolic Laplace/Fourier/z-transforms, convolutions, partial fractions, pole/zero locations, sampling and aliasing checks, etc. The tool cannot see any figure, so if you need values from a figure, read them yourself and type them into your code. Never guess or invent tool output; base your conclusion on what the tool actually printed. You may call the tool at most {max_tool_rounds} times in total; you can answer directly if no computation is needed.

### Final answer format
When you are done, reply with strictly a valid JSON object with ONLY these two keys and nothing else. Ensure all quotes and newlines inside the reasoning string are properly escaped for JSON. Do not use markdown blocks.
{{
 "reasoning": "Step-by-step logical evaluation of the options, including what any computation showed.",
 "answer": "Single uppercase letter matching the correct option."
}}"""
    if img_path and "images_merged" in img_path:
        return f"""Solve the following multiple-choice exam question.
<question>{q.get('question')}
</question>
<options>The options are fully visible in the attached image.
</options>
{instructions}"""
    return f"""Solve the following multiple-choice exam question.
<question>{q.get('question')}
</question>
<options>{options_str}
</options>
{instructions}"""


# ----------------------------------------------------------------------------
# API + tool loop
# ----------------------------------------------------------------------------
def chat(endpoint, api_key, model_name, messages, tool_choice, enable_thinking, timeout=180):
    """One chat-completion call with transient-error retries. Returns the assistant message dict."""
    payload = {
        "model": model_name,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": tool_choice,
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    for attempt in range(3):
        enforce_rate_limit()
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"),
                                     headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            if "choices" not in result or not result["choices"]:
                raise ValueError(f"Unexpected API response structure: {result}")
            return result["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"    HTTP {e.code}. Retrying in {wait}s...")
                time.sleep(wait)
                continue
            body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            raise RuntimeError(f"HTTP Error {e.code}: {e.reason} {body[:500]}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as ex:
            if attempt < 2:
                wait = 5 * (2 ** attempt)
                print(f"    Network error ({ex}). Retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise


def run_episode(endpoint, api_key, model_name, user_content, valid_options, max_tool_rounds,
                enable_thinking, exec_timeout, mem_mb, debug):
    """
    Runs the tool loop for one question.
    Returns (reasoning, answer, trace). Raises ValueError if no valid answer is produced.
    """
    messages = [{"role": "user", "content": user_content}]
    trace = {"turns": [], "tool_calls_used": 0}
    calls_used = 0

    for _turn in range(max_tool_rounds + 3):
        tool_choice = "required" #"auto" if calls_used < max_tool_rounds else "none"
        msg = chat(endpoint, api_key, model_name, messages, tool_choice, enable_thinking)
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if tool_calls and tool_choice == "auto":
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            turn_log = {"assistant_content": content, "tool_calls": []}
            for tc in tool_calls:
                fn = tc.get("function", {})
                tc_id = tc.get("id", "")
                if calls_used >= max_tool_rounds:
                    result = "ERROR: tool-call budget exhausted. Give your final JSON answer now."
                    code = None
                else:
                    try:
                        args = fn.get("arguments", "{}")
                        args = json.loads(args) if isinstance(args, str) else args
                        code = args.get("code")
                    except Exception:
                        args, code = None, None
                    if fn.get("name") != "run_python":
                        result = f"ERROR: unknown tool '{fn.get('name')}'. Only run_python exists."
                    elif not isinstance(code, str):
                        result = "ERROR: arguments must be a JSON object with a string field `code`."
                    else:
                        result = run_python(code, timeout=exec_timeout, mem_mb=mem_mb)
                    calls_used += 1
                    if debug:
                        print(f"    [tool] code:\n{code}\n    [tool] output:\n{result}")
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                turn_log["tool_calls"].append({"id": tc_id, "code": code, "output": result})
            trace["turns"].append(turn_log)
            continue

        # No (usable) tool call: treat as the final answer.
        reasoning, answer = parse_model_output(content)
        trace["turns"].append({"assistant_content": content, "tool_calls": []})
        if answer and answer in valid_options:
            trace["tool_calls_used"] = calls_used
            return reasoning, answer, trace
        # Nudge once toward the required format.
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content":
                         'Reply now with ONLY the JSON object {"reasoning": "...", "answer": "<single letter>"} '
                         f"where the answer is one of {valid_options}. Do not call any more tools."})
        calls_used = max(calls_used, max_tool_rounds)  # force tool_choice="none" from here

    trace["tool_calls_used"] = calls_used
    raise ValueError("No valid answer produced after tool loop.")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def check_sandbox():
    out = run_python("import numpy, scipy, sympy\nprint('ok')", timeout=60)
    if out.strip() != "ok":
        print(f"WARNING: sandbox self-check failed (numpy/scipy/sympy missing?). Output:\n{out}")


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def solve_exam(exam_dir, exam_id, model_name, api_key, endpoint=DEFAULT_ENDPOINT, enable_thinking=False,
               max_tool_rounds=3, exec_timeout=20, mem_mb=2048, is_debug_run=False,
               target_question_id=None, output_json=None):
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = output_json or f"processed-data/tool-harness/{model_name}/solutions_tools_{exam_id}.json"
    trace_json = os.path.join(os.path.dirname(output_json),
                              os.path.basename(output_json).replace("solutions_", "traces_", 1))

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} (Directory: {exam_dir}) using model: {model_name} "
          f"(Tool Harness, max_tool_rounds={max_tool_rounds}, Thinking: {enable_thinking}) ---")
    check_sandbox()

    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)
    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    if target_question_id:
        questions = [q for q in questions if q.get("id") == target_question_id]
        if not questions:
            print(f"Error: Question ID '{target_question_id}' not found in exam data.")
            return False
        print(f"--> Isolation Mode Enabled: Testing ONLY Question ID: {target_question_id}")

    all_answers, traces, done = [], {}, set()
    if os.path.exists(output_json) and not target_question_id:
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                all_answers = json.load(f).get("answers", [])
            done = {a["id"] for a in all_answers}
            if os.path.exists(trace_json):
                with open(trace_json, "r", encoding="utf-8") as f:
                    traces = json.load(f).get("traces", {})
            print(f"Resuming exam: found {len(done)} already answered questions.")
        except Exception:
            pass

    for idx, q in enumerate(questions):
        q_id = q.get("id", f"q{idx+1}")
        if q_id in done and not target_question_id:
            print(f"Skipping already completed question: {q_id}")
            continue
        print(f"Processing question {idx + 1}/{len(questions)} (ID: {q_id})...", flush=True)

        img_path = resolve_and_verify_image_path(exam_dir, q.get("image_path"))
        base64_url = encode_image_to_base64(img_path) if img_path else None
        options_str = json.dumps(q.get("options", {}), indent=2)
        prompt = build_prompt(q, options_str, img_path if base64_url else None, max_tool_rounds)
        user_content = [{"type": "text", "text": prompt}]
        if base64_url:
            user_content.append({"type": "image_url", "image_url": {"url": base64_url}})

        valid_options = list(q.get("options", {}).keys()) or list("ABCDEFGHIJKLMNO")

        success = False
        for attempt in range(3):
            try:
                print(f"  -> Attempt {attempt + 1}/3 for {q_id}...", flush=True)
                reasoning, answer, trace = run_episode(
                    endpoint, api_key, model_name, user_content, valid_options, max_tool_rounds,
                    enable_thinking, exec_timeout, mem_mb, is_debug_run)
                all_answers = [a for a in all_answers if a.get("id") != q_id]
                all_answers.append({"id": q_id, "reasoning": reasoning, "answer": answer})
                traces[q_id] = trace
                save_json(output_json, {"examId": exam_data.get('examId', exam_id),
                                        "examTitle": "Signals & Systems Solutions (Tool Harness)",
                                        "model": model_name, "answers": all_answers})
                save_json(trace_json, {"examId": exam_data.get('examId', exam_id), "model": model_name,
                                       "traces": traces})
                print(f"  -> Successfully processed {q_id}! (tool calls used: {trace['tool_calls_used']})")
                success = True
                break
            except Exception as ex:
                print(f"  Attempt {attempt + 1} failed for question {q_id}: {ex}")
                time.sleep(2)
        if not success:
            print(f"Warning: Question {q_id} failed after retries.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an LLM on MC exam questions with a native python tool.")
    parser.add_argument("--exam_dir", type=str, required=True)
    parser.add_argument("--exam_id", type=str, required=True)
    parser.add_argument("--model_name", type=str, required=True)
    parser.add_argument("--api_key", type=str, default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""))
    parser.add_argument("--endpoint", type=str, default=DEFAULT_ENDPOINT)
    parser.add_argument("--enable_thinking", action="store_true")
    parser.add_argument("--max_tool_rounds", type=int, default=3, help="Max run_python calls per question")
    parser.add_argument("--exec_timeout", type=int, default=20, help="Seconds per code execution")
    parser.add_argument("--exec_mem_mb", type=int, default=2048, help="Memory limit per execution (POSIX)")
    parser.add_argument("--rate_per_min", type=float, default=14.0, help="Max API calls per minute")
    parser.add_argument("--question_id", type=str, default=None)
    parser.add_argument("--output_json", type=str, default=None,
                        help="Override the solutions path (e.g. to keep one file per model)")
    parser.add_argument("--debug", action="store_true", help="Print executed code and outputs")
    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("API key must be provided via --api_key or the SWISSAI_RESEARCH_API_KEY environment variable.")
    MIN_API_INTERVAL = 60.0 / args.rate_per_min

    solve_exam(exam_dir=args.exam_dir, exam_id=args.exam_id, model_name=args.model_name, api_key=args.api_key,
               endpoint=args.endpoint, enable_thinking=args.enable_thinking, max_tool_rounds=args.max_tool_rounds,
               exec_timeout=args.exec_timeout, mem_mb=args.exec_mem_mb, is_debug_run=args.debug,
               target_question_id=args.question_id, output_json=args.output_json)
