"""
MULTI-AGENT DEBATE, FREE-TEXT

Round 1: every debater solves the problem independently.
Round 2: every debater reads its peers' solutions, critiques them, and writes a revised solution.
Round 3: a judge reads the full transcript and writes the final solution.

The output file has exactly the same schema as solve_exam_b_freetext.py
(answers -> [{id, parts: [{id, work, final}]}]), so the same grader can be used.
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

OUTPUT_FORMAT = """For each part write your complete step-by-step derivation, then a concise final answer, using exactly this format (no text outside these blocks):
<part id="PART_ID">
<work>your derivation</work>
<final>your final answer</final>
</part>
Write mathematics in LaTeX or plain text. The number of points per part indicates the expected depth of the answer. If a part refers to a figure, use the attached image(s)."""


# ----------------------------------------------------------------------------
# Prompt builders
# ----------------------------------------------------------------------------
def problem_block(q):
    """Whitelist-only problem + parts block (identical to the reason-then-answer prompt)."""
    parts_xml = []
    for p in q["parts"]:
        note = "\n(This part refers to an attached figure.)" if p.get("image_path") else ""
        parts_xml.append(f'<part id="{p["id"]}" points="{p["points"]}">\n{p["question"]}{note}\n</part>')
    return f"""<problem>
{q.get('question', '')}
</problem>
<parts>
{chr(10).join(parts_xml)}
</parts>"""


def format_solution(parts):
    """Renders a parsed solution back into the <part><work><final> format."""
    return "\n".join(
        f'<part id="{p["id"]}">\n<work>{p["work"]}</work>\n<final>{p["final"]}</final>\n</part>'
        for p in parts)


def build_round1_prompt(q):
    return f"""Solve the following exam problem from a Signals & Systems course. Show your work for every part.

{problem_block(q)}

### Instructions
Answer EVERY part. {OUTPUT_FORMAT}"""


def build_round2_prompt(q, agent_name, round1):
    """Cross-critique prompt: the agent sees its own and its peers' Round 1 solutions."""
    own = format_solution(round1[agent_name]["parts"]) if agent_name in round1 else "(no solution)"
    peers_text = ""
    for name, res in round1.items():
        if name != agent_name:
            peers_text += f"\n=== Solution by {name} ===\n{format_solution(res['parts'])}\n"
    if not peers_text:
        peers_text = "\n(No peer solutions are available.)\n"

    return f"""You are participating in a multi-agent debate to solve an exam problem from a Signals & Systems course.

{problem_block(q)}

Your own independent solution from Round 1:
=== Solution by {agent_name} (you) ===
{own}

The independent solutions proposed by your fellow expert agents in Round 1:
{peers_text}
### Instructions
Critically compare the solutions part by part. Check each derivation for errors (signs, factors of 2*pi, scaling and shifting, convergence conditions, region of convergence, etc.) and decide which reasoning is correct, including your own. Where solutions disagree, work out which one is right.
Then write your final, revised solution to EVERY part. Begin each <work> block with a short critique of where the solutions agree or disagree and what you changed (if anything), followed by your complete corrected derivation. {OUTPUT_FORMAT}"""


def build_judge_prompt(q, transcript):
    transcript_text = ""
    for round_name, agents in transcript.items():
        transcript_text += f"\n######## {round_name} ########\n"
        for agent_name, res in agents.items():
            transcript_text += f"\n=== {agent_name} ===\n{format_solution(res['parts'])}\n"

    return f"""You are the lead judge reviewing a multi-agent debate between expert agents on an exam problem from a Signals & Systems course.

{problem_block(q)}

Debate transcript:
{transcript_text}
### Instructions
For every part, analyze how the arguments progressed across the rounds, verify the mathematics yourself, and determine the correct result. Do not simply follow the majority: if all agents share an error, correct it.
Then write the definitive solution to EVERY part. {OUTPUT_FORMAT}"""


# ----------------------------------------------------------------------------
# Parsing / API helpers
# ----------------------------------------------------------------------------
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


def build_messages(prompt, image_urls):
    content = [{"type": "text", "text": prompt}]
    for url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": url}})
    return [{"role": "user", "content": content}]


def query_parts(model, api_key, prompt, image_urls, expected_ids, enable_thinking, debug, label, retries=3):
    """Calls the model until all expected parts parse. Returns (parts, raw). Raises after `retries` failures."""
    messages = build_messages(prompt, image_urls)
    last_err = None
    for attempt in range(retries):
        raw = None
        try:
            raw = call_llm(model, api_key, messages, temperature=0.1,
                           enable_thinking=enable_thinking, json_mode=False)
            parts, missing = parse_parts(raw, expected_ids)
            if missing:
                raise ValueError(f"Missing parts in output: {missing}")
            return parts, raw
        except Exception as ex:
            last_err = ex
            print(f"     Attempt {attempt + 1}/{retries} failed for {label}: {ex}")
            if debug and raw is not None:
                print("--- RAW OUTPUT ---\n" + raw + "\n--- END ---")
    raise RuntimeError(f"{label} failed after {retries} attempts: {last_err}")


def short_name(model_name):
    return MODEL_ID.get(model_name, re.sub(r"[^A-Za-z0-9._-]+", "_", model_name.split("/")[-1]))


# ----------------------------------------------------------------------------
# Main loop
# ----------------------------------------------------------------------------
def solve_exam(exam_dir, exam_id, debater_models, judge_model, api_key, enable_thinking=False, debug=False,
               target_question_id=None, save_transcript=False):
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = f"processed-data/multi-agent-debate/{short_name(judge_model)}/solutions_{exam_id}.json"
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

    print(f"\n--- Solving {exam_id} ({exam_dir}) with Multi-Agent Debate (thinking={enable_thinking}) ---")
    print(f"Debaters: {debater_models}\nJudge: {judge_model}")

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
        print(f"\nProblem {idx + 1}/{len(questions)} ({q_id}, {len(q['parts'])} parts)...", flush=True)

        parts_expected = [p["id"] for p in q["parts"]]
        image_urls = [u for u in (encode_image_to_base64(ip) for ip in collect_images(exam_dir, q)) if u]
        agent_names = [f"Agent_{i + 1}" for i in range(len(debater_models))]

        # ---------------- Round 1: independent generation ----------------
        print("  -> [Round 1] Independent generation...", flush=True)
        r1_prompt = build_round1_prompt(q)
        round1 = {}
        for name, model in zip(agent_names, debater_models):
            try:
                parts, raw = query_parts(model, api_key, r1_prompt, image_urls, parts_expected,
                                         enable_thinking, debug, f"{q_id}/{name}/R1")
                round1[name] = {"model": model, "parts": parts}
                print(f"     - {name} ({model}): done.")
            except Exception as ex:
                print(f"     - {name} excluded from debate: {ex}")

        if not round1:
            print(f"Warning: {q_id} failed (no debater produced a valid Round 1 solution).")
            continue

        # ---------------- Round 2: cross-critique ----------------
        print("  -> [Round 2] Cross-critique and revision...", flush=True)
        round2 = {}
        for name, model in zip(agent_names, debater_models):
            if name not in round1:
                continue
            r2_prompt = build_round2_prompt(q, name, round1)
            try:
                parts, raw = query_parts(model, api_key, r2_prompt, image_urls, parts_expected,
                                         enable_thinking, debug, f"{q_id}/{name}/R2")
                round2[name] = {"model": model, "parts": parts}
                print(f"     - {name} ({model}): revised.")
            except Exception as ex:
                print(f"     - {name} failed in Round 2, keeping Round 1: {ex}")
                round2[name] = round1[name]

        transcript = {"Round_1": round1, "Round_2": round2}

        # ---------------- Round 3: judge ----------------
        print(f"  -> [Round 3] Judge adjudication using {judge_model}...", flush=True)
        judge_used = True
        try:
            final_parts, _ = query_parts(judge_model, api_key, build_judge_prompt(q, transcript), image_urls,
                                         parts_expected, enable_thinking, debug, f"{q_id}/judge")
        except Exception as ex:
            # Fallback: take the first available Round 2 solution (agents are listed in priority order).
            fb_name = next(iter(round2))
            print(f"     - Judge failed: {ex}. Falling back to {fb_name}'s Round 2 solution.")
            final_parts = round2[fb_name]["parts"]
            judge_used = False

        entry = {"id": q_id, "parts": final_parts}
        if save_transcript:
            entry["debate_transcript"] = transcript
            entry["judge_fallback_used"] = not judge_used

        all_answers = [a for a in all_answers if a["id"] != q_id] + [entry]
        os.makedirs(os.path.dirname(output_json), exist_ok=True)
        with open(output_json, "w", encoding="utf-8") as f:
            json.dump({"examId": exam_data.get("examId", exam_id),
                       "examTitle": "Signals & Systems Free-Text Solutions (Multi-Agent Debate)",
                       "model": judge_model, "answers": all_answers}, f, indent=2, ensure_ascii=False)
        print(f"  -> {q_id} done.")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Solve free-text exam problems via multi-agent debate (SwissAI API).")
    ap.add_argument("--exam_dir", required=True)
    ap.add_argument("--exam_id", required=True, help="e.g. 2019_autumn_freetext")
    ap.add_argument("--debater_models", required=True, help="Comma-separated debater model names (e.g. modelA,modelB,modelC)")
    ap.add_argument("--judge_model", required=True, help="Judge model name")
    ap.add_argument("--api_key", default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""))
    ap.add_argument("--enable_thinking", action="store_true")
    ap.add_argument("--question_id", default=None, help="Solve a single problem, e.g. q4")
    ap.add_argument("--save_transcript", action="store_true",
                    help="Store the Round 1/2 debate transcript in each answer entry (extra keys; the grader can ignore them)")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if not a.api_key:
        raise ValueError("Provide --api_key or set SWISSAI_RESEARCH_API_KEY.")
    debaters = [m.strip() for m in a.debater_models.split(",") if m.strip()]
    if len(debaters) < 2:
        raise ValueError("Provide at least 2 comma-separated debater models.")
    solve_exam(a.exam_dir, a.exam_id, debaters, a.judge_model, a.api_key, a.enable_thinking, a.debug,
               a.question_id, a.save_transcript)
