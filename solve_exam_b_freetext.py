"""
REASON-THEN-ANSWER, FREE-TEXT
"""
import os
import re
import json
import argparse
from swissai_client import (call_llm, encode_image_to_base64, resolve_image_path, split_think)

PART_RE = re.compile(r"<part\s+id\s*=\s*[\"']([^\"']+)[\"']\s*>(.*?)</part>", re.DOTALL)
MODEL_ID = {"CSCS-Inference/swiss-ai/Apertus-v1.5-70B": "Apertus-v1.5-70B", 
"RCP-AIaaS/deepseek-ai/DeepSeek-V4.1-Flash-1017": "DeepSeek", 
"CSCS-Inference/google/gemma-4-31B-it": "Gemma-4", 
"SwissAI-Research/Qwen/Qwen3.8-27B": "Qwen3.8-27B"}

def build_prompt(q):
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

### Instructions
Answer EVERY part. For each part write your complete step-by-step derivation, then a concise final answer, using exactly this format (no text outside these blocks):
<part id="PART_ID">
<work>your derivation</work>
<final>your final answer</final>
</part>
Write mathematics in LaTeX or plain text. The number of points per part indicates the expected depth of the answer. If a part refers to a figure, use the attached image(s)."""


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
        rp = resolve_image_path(exam_dir, p.get("image_path"))
        if rp and rp not in paths:
            paths.append(rp)
    return paths


def solve_exam(exam_dir, exam_id, model_name, api_key, enable_thinking=False, debug=False,
               target_question_id=None, save_raw=False):
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    model_dir = MODEL_ID[model_name]
    output_json = f"processed-data/reason-then-answer/{model_dir}/solutions_{exam_id}.json"
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

    print(f"\n--- Solving {exam_id} ({exam_dir}) with {model_name} (thinking={enable_thinking}) ---")

    all_answers, done = [], set()
    if os.path.exists(output_json) and not target_question_id:
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                all_answers = json.load(f).get("answers", [])
            done = {a["id"] for a in all_answers}
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
        content = [{"type": "text", "text": build_prompt(q)}]
        for ip in collect_images(exam_dir, q):
            url = encode_image_to_base64(ip)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        messages = [{"role": "user", "content": content}]

        success = False
        for attempt in range(3):
            raw = None
            try:
                raw = call_llm(model_name, api_key, messages, temperature=0.1,
                               enable_thinking=enable_thinking, json_mode=False)
                parts, missing = parse_parts(raw, parts_expected)
                if missing:
                    raise ValueError(f"Missing parts in output: {missing}")
                entry = {"id": q_id, "parts": parts}
                if save_raw:
                    entry["raw_output"] = raw
                all_answers = [a for a in all_answers if a["id"] != q_id] + [entry]
                os.makedirs(os.path.dirname(output_json), exist_ok=True)
                with open(output_json, "w", encoding="utf-8") as f:
                    json.dump({"examId": exam_data.get("examId", exam_id),
                               "examTitle": "Signals & Systems Free-Text Solutions (Reason-Then-Answer)",
                               "model": model_name, "answers": all_answers}, f, indent=2, ensure_ascii=False)
                print(f"  -> {q_id} done.")
                success = True
                break
            except Exception as ex:
                print(f"  Attempt {attempt + 1}/3 failed for {q_id}: {ex}")
                if debug and raw is not None:
                    print("--- RAW OUTPUT ---\n" + raw + "\n--- END ---")
        if not success:
            print(f"Warning: {q_id} failed after retries.")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Solve free-text exam problems via SwissAI API.")
    ap.add_argument("--exam_dir", required=True)
    ap.add_argument("--exam_id", required=True, help="e.g. 2019_autumn_freetext")
    ap.add_argument("--model_name", required=True)
    ap.add_argument("--api_key", default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""))
    ap.add_argument("--enable_thinking", action="store_true")
    ap.add_argument("--question_id", default=None, help="Solve a single problem, e.g. q4")
    ap.add_argument("--save_raw", action="store_true", help="Store the raw model output per problem")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if not a.api_key:
        raise ValueError("Provide --api_key or set SWISSAI_RESEARCH_API_KEY.")
    solve_exam(a.exam_dir, a.exam_id, a.model_name, a.api_key, a.enable_thinking, a.debug,
               a.question_id, a.save_raw)
