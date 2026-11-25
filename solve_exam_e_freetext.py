"""
TOOL-HARNESS, FREE-TEXT (native tool calling with a sandboxed `run_python` tool)

Free-text counterpart of solve_exam_e.py (tool harness, MC), mirroring solve_exam_b_freetext.py
(reason-then-answer, free-text). The model may call `run_python` a limited number of times to compute
or verify results (numpy / scipy / sympy), then must answer EVERY part in exactly the same block format
as solve_exam_b_freetext.py:

    <part id="PART_ID">
    <work>derivation</work>
    <final>final answer</final>
    </part>

Outputs
  processed-data/tool-harness/{model_dir}/solutions_tools_{exam_id}.json
      -> SAME schema as solve_exam_b_freetext.py, so the same grader can be used:
         {"examId", "examTitle", "model", "answers": [{"id", "parts": [{"id", "work", "final"}]}]}
  processed-data/tool-harness/{model_dir}/traces_tools_{exam_id}.json
      -> per-problem tool trace (code, outputs, turns), for analysis.

The sandbox, tool schema, rate limiter, API call and image helpers are imported from solve_exam_e.py
(must be in the same directory) so tool behaviour is identical across the MC and free-text harnesses.
"""
import os
import re
import json
import time
import argparse

import solve_exam_e as E  # run_python, TOOLS, chat, enforce_rate_limit, image helpers, save_json, check_sandbox

PART_RE = re.compile(r"<part\s+id\s*=\s*[\"']([^\"']+)[\"']\s*>(.*?)</part>", re.DOTALL)
MODEL_ID = {"CSCS-Inference/swiss-ai/Apertus-v1.5-70B": "Apertus-v1.5-70B",
            "RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash-1017": "DeepSeek",
            "CSCS-Inference/google/gemma-4-31B-it": "Gemma-4",
            "SwissAI-Research/Qwen/Qwen3.8-27B": "Qwen3.8-27B"}


# ----------------------------------------------------------------------------
# Prompt (same problem/parts rendering as solve_exam_b_freetext.py + tool instructions)
# ----------------------------------------------------------------------------
def build_prompt(q, max_tool_rounds):
    """Whitelist-only prompt builder."""
    parts_xml = []
    for p in q["parts"]:
        note = "\n(This part refers to an attached figure.)" if p.get("image_path") else ""
        parts_xml.append(f'<part id="{p["id"]}" points="{p["points"]}">\n{p["question"]}{note}\n</part>')
    return f"""Solve the following exam problem from a Signals & Systems course. Show your work for every part.

<problem>
{q.get('question', '')}
</problem>
<parts>
{chr(10).join(parts_xml)}
</parts>

### Tool use
You have a `run_python` tool (Python 3 with numpy, scipy, sympy). Use it when it helps you compute or verify a result: numerical evaluation, symbolic Laplace/Fourier/z-transforms, convolutions, partial fractions, pole/zero locations, sampling and aliasing checks, etc. The tool cannot see any figure, so if you need values from a figure, read them yourself and type them into your code. Never guess or invent tool output; base your conclusion on what the tool actually printed. You may call the tool at most {max_tool_rounds} times in total across ALL parts of this problem; you can answer directly if no computation is needed.

### Final answer format
Answer EVERY part. When you are done with any tool use, write for each part your complete step-by-step derivation (including what any computation showed), then a concise final answer, using exactly this format (no text outside these blocks):
<part id="PART_ID">
<work>your derivation</work>
<final>your final answer</final>
</part>
Write mathematics in LaTeX or plain text. The number of points per part indicates the expected depth of the answer. If a part refers to a figure, use the attached image(s)."""


# ----------------------------------------------------------------------------
# Parsing (same behaviour as solve_exam_b_freetext.py)
# ----------------------------------------------------------------------------
def split_think(raw):
    """Returns (think_text, visible_text). Handles <think>...</think> and a dangling </think>."""
    raw = raw or ""
    m = re.search(r"<think>(.*?)</think>", raw, re.DOTALL)
    if m:
        return m.group(1).strip(), re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if "</think>" in raw:  # template already opened the think block
        think, _, visible = raw.rpartition("</think>")
        return think.strip(), visible.strip()
    return "", raw.strip()


def parse_parts(raw, expected_ids):
    """Returns (parts_list, missing_ids). Tolerates a missing <work>/<final> split."""
    _, visible = split_think(raw)
    found = {}
    for pid, body in PART_RE.findall(visible):
        w = re.search(r"<work>(.*?)</work>", body, re.DOTALL)
        f = re.search(r"<final>(.*?)</final>", body, re.DOTALL)
        work = w.group(1).strip() if w else body.strip()
        final = f.group(1).strip() if f else ""
        found[pid.strip()] = {"id": pid.strip(), "work": work, "final": final}
    missing = [i for i in expected_ids if i not in found]
    return [found[i] for i in expected_ids if i in found], missing


def collect_images(exam_dir, q):
    paths = []
    for p in [q] + q["parts"]:
        rp = E.resolve_and_verify_image_path(exam_dir, p.get("image_path"))
        if rp and rp not in paths:
            paths.append(rp)
    return paths


# ----------------------------------------------------------------------------
# Tool loop
# ----------------------------------------------------------------------------
def run_episode(endpoint, api_key, model_name, user_content, expected_ids, max_tool_rounds,
                enable_thinking, exec_timeout, mem_mb, debug):
    """
    Runs the tool loop for one problem.
    Returns (parts, final_raw_content, trace). Raises ValueError if not all parts are produced.
    """
    messages = [{"role": "user", "content": user_content}]
    trace = {"turns": [], "tool_calls_used": 0}
    calls_used = 0   # budget counter (also bumped to force tool_choice="none" after a nudge)
    executed = 0     # tool calls actually run, reported in the trace

    for _turn in range(max_tool_rounds + 4):
        tool_choice = "auto" if calls_used < max_tool_rounds else "none"
        msg = E.chat(endpoint, api_key, model_name, messages, tool_choice, enable_thinking)
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or []

        if tool_calls and tool_choice == "auto":
            messages.append({"role": "assistant", "content": content, "tool_calls": tool_calls})
            turn_log = {"assistant_content": content, "tool_calls": []}
            for tc in tool_calls:
                fn = tc.get("function", {})
                tc_id = tc.get("id", "")
                if calls_used >= max_tool_rounds:
                    result = "ERROR: tool-call budget exhausted. Give your final answer blocks now."
                    code = None
                else:
                    try:
                        args = fn.get("arguments", "{}")
                        args = json.loads(args) if isinstance(args, str) else args
                        code = args.get("code")
                    except Exception:
                        code = None
                    if fn.get("name") != "run_python":
                        result = f"ERROR: unknown tool '{fn.get('name')}'. Only run_python exists."
                    elif not isinstance(code, str):
                        result = "ERROR: arguments must be a JSON object with a string field `code`."
                    else:
                        result = E.run_python(code, timeout=exec_timeout, mem_mb=mem_mb)
                        executed += 1
                    calls_used += 1
                    if debug:
                        print(f"    [tool] code:\n{code}\n    [tool] output:\n{result}")
                messages.append({"role": "tool", "tool_call_id": tc_id, "content": result})
                turn_log["tool_calls"].append({"id": tc_id, "code": code, "output": result})
            trace["turns"].append(turn_log)
            continue

        # No (usable) tool call: treat as the final answer.
        parts, missing = parse_parts(content, expected_ids)
        trace["turns"].append({"assistant_content": content, "tool_calls": []})
        if not missing:
            trace["tool_calls_used"] = executed
            return parts, content, trace
        # Nudge toward the required format (and the missing parts).
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content":
                         "Reply now with ONLY the answer blocks, in exactly this format for EVERY part, "
                         "including parts you already wrote:\n"
                         '<part id="PART_ID">\n<work>...</work>\n<final>...</final>\n</part>\n'
                         f"Required part ids: {expected_ids}. Missing from your last reply: {missing}. "
                         "Do not call any more tools."})
        calls_used = max(calls_used, max_tool_rounds)  # force tool_choice="none" from here

    trace["tool_calls_used"] = executed
    raise ValueError("Missing parts after tool loop (no complete answer produced).")


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def solve_exam(exam_dir, exam_id, model_name, api_key, endpoint=E.DEFAULT_ENDPOINT, enable_thinking=False,
               max_tool_rounds=5, exec_timeout=20, mem_mb=2048, debug=False,
               target_question_id=None, save_raw=False, output_json=None):
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    model_dir = MODEL_ID.get(model_name, model_name.replace("/", "_"))
    output_json = output_json or f"processed-data/tool-harness/{model_dir}/solutions_tools_{exam_id}.json"
    trace_json = os.path.join(os.path.dirname(output_json),
                              os.path.basename(output_json).replace("solutions_", "traces_", 1))
    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False
    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)
    questions = exam_data.get("questions", [])
    if target_question_id:
        questions = [q for q in questions if q.get("id") == target_question_id]
        if not questions:
            print(f"Error: Question ID '{target_question_id}' not found.")
            return False
        print(f"--> Isolation mode: ONLY {target_question_id}")

    print(f"\n--- Solving {exam_id} ({exam_dir}) with {model_name} "
          f"(Tool Harness, max_tool_rounds={max_tool_rounds}, thinking={enable_thinking}) ---")
    E.check_sandbox()

    all_answers, traces, done = [], {}, set()
    if os.path.exists(output_json) and not target_question_id:
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                all_answers = json.load(f).get("answers", [])
            done = {a["id"] for a in all_answers}
            if os.path.exists(trace_json):
                with open(trace_json, "r", encoding="utf-8") as f:
                    traces = json.load(f).get("traces", {})
            print(f"Resuming: {len(done)} problems already answered.")
        except Exception:
            pass

    for idx, q in enumerate(questions):
        q_id = q["id"]
        if q_id in done and not target_question_id:
            print(f"Skipping completed problem {q_id}")
            continue
        print(f"Problem {idx + 1}/{len(questions)} ({q_id}, {len(q['parts'])} parts)...", flush=True)

        parts_expected = [p["id"] for p in q["parts"]]
        content = [{"type": "text", "text": build_prompt(q, max_tool_rounds)}]
        for ip in collect_images(exam_dir, q):
            url = E.encode_image_to_base64(ip)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})

        success = False
        for attempt in range(3):
            try:
                print(f"  -> Attempt {attempt + 1}/3 for {q_id}...", flush=True)
                parts, raw, trace = run_episode(endpoint, api_key, model_name, content, parts_expected,
                                                max_tool_rounds, enable_thinking, exec_timeout, mem_mb, debug)
                entry = {"id": q_id, "parts": parts}
                if save_raw:
                    entry["raw_output"] = raw
                all_answers = [a for a in all_answers if a["id"] != q_id] + [entry]
                traces[q_id] = trace
                E.save_json(output_json, {"examId": exam_data.get("examId", exam_id),
                                          "examTitle": "Signals & Systems Free-Text Solutions (Tool Harness)",
                                          "model": model_name, "answers": all_answers})
                E.save_json(trace_json, {"examId": exam_data.get("examId", exam_id), "model": model_name,
                                         "traces": traces})
                print(f"  -> {q_id} done. (tool calls used: {trace['tool_calls_used']})")
                success = True
                break
            except Exception as ex:
                print(f"  Attempt {attempt + 1}/3 failed for {q_id}: {ex}")
                time.sleep(2)
        if not success:
            print(f"Warning: {q_id} failed after retries.")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Solve free-text exam problems via SwissAI API with a native python tool.")
    ap.add_argument("--exam_dir", required=True)
    ap.add_argument("--exam_id", required=True, help="e.g. 2019_autumn_freetext")
    ap.add_argument("--model_name", required=True)
    ap.add_argument("--api_key", default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""))
    ap.add_argument("--endpoint", default=E.DEFAULT_ENDPOINT)
    ap.add_argument("--enable_thinking", action="store_true")
    ap.add_argument("--max_tool_rounds", type=int, default=5,
                    help="Max run_python calls per problem (shared across all its parts)")
    ap.add_argument("--exec_timeout", type=int, default=20, help="Seconds per code execution")
    ap.add_argument("--exec_mem_mb", type=int, default=2048, help="Memory limit per execution (POSIX)")
    ap.add_argument("--rate_per_min", type=float, default=14.0, help="Max API calls per minute")
    ap.add_argument("--question_id", default=None, help="Solve a single problem, e.g. q4")
    ap.add_argument("--output_json", default=None, help="Override the solutions path")
    ap.add_argument("--save_raw", action="store_true", help="Store the final raw model output per problem")
    ap.add_argument("--debug", action="store_true", help="Print executed code and outputs")
    a = ap.parse_args()
    if not a.api_key:
        raise ValueError("Provide --api_key or set SWISSAI_RESEARCH_API_KEY.")
    E.MIN_API_INTERVAL = 60.0 / a.rate_per_min  # enforce_rate_limit() in solve_exam_e reads this global
    solve_exam(a.exam_dir, a.exam_id, a.model_name, a.api_key, a.endpoint, a.enable_thinking,
               a.max_tool_rounds, a.exec_timeout, a.exec_mem_mb, a.debug, a.question_id, a.save_raw,
               a.output_json)
