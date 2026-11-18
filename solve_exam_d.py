"""
Multi-agent Debate
"""
import os
import json
import time
import socket
import base64
import argparse
import urllib.request
import urllib.error
import re

# Global tracker for rate limiting (max 14 calls per minute -> ~4.3 seconds interval)
_LAST_API_CALL_TIME = 0.0
MIN_API_INTERVAL = 60.0 / 14.0  # ~4.285 seconds


def enforce_rate_limit():
    """Ensures at least MIN_API_INTERVAL seconds have passed since the last API call."""
    global _LAST_API_CALL_TIME
    elapsed = time.time() - _LAST_API_CALL_TIME
    if elapsed < MIN_API_INTERVAL:
        time.sleep(MIN_API_INTERVAL - elapsed)
    _LAST_API_CALL_TIME = time.time()


def encode_image_to_base64(image_path):
    """Encodes a local image file into a base64 data URL."""
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")
            ext = image_path.split('.')[-1].lower()
            mime = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/png"
            return f"data:{mime};base64,{encoded}"
    return None


def resolve_and_verify_image_path(exam_dir, img_path):
    """Checks if the image path is provided and verifies the file exists on disk."""
    if not img_path:
        return None
    if os.path.exists(img_path):
        return img_path
    candidate = os.path.join("data", exam_dir, img_path)
    if os.path.exists(candidate):
        return candidate
    print(f"Warning: Image path specified ('{img_path}') but file does not exist on disk. Proceeding as text-only.")
    return None


def extract_json_safely(raw_content):
    """Extract a JSON object from raw model output, stripping markdown fences."""
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
    """
    Returns (reasoning, answer) from raw model output.
    Reasoning priority: <reasoning> tags -> JSON 'reasoning' key -> <think> tags.
    Answer: JSON 'answer' key, with a regex fallback if the JSON is malformed.
    """
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
    if not reasoning:
        reasoning = ""

    return reasoning, answer


def build_round1_prompt(q, options_str, img_path):
    """Builds the initial user prompt for Round 1 (Independent Generation)."""
    instructions = """### Instructions
Return strictly a valid JSON object with ONLY these two keys and nothing else. Ensure all quotes and newlines inside the reasoning string are properly escaped for JSON. Do not use markdown blocks.
{
 "reasoning": "Step-by-step logical evaluation of the options.",
 "answer": "Single uppercase letter matching the correct option."
}"""

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


def build_round2_prompt(q, options_str, agent_name, peer_results):
    """Builds the prompt for Round 2 (Cross-Critique & Debate)."""
    peers_text = ""
    for peer_name, res in peer_results.items():
        if peer_name != agent_name:
            peers_text += f"\n- **{peer_name}** chose **{res['answer']}** with this reasoning:\n\"{res['reasoning']}\"\n"

    instructions = """### Instructions
Review your peers' arguments above. Critically evaluate whether their logic or your initial reasoning is correct. 
Return strictly a valid JSON object with ONLY these two keys and nothing else. Ensure all quotes and newlines inside the reasoning string are properly escaped for JSON. Do not use markdown blocks.
{
 "reasoning": "Critique of peer perspectives and revised step-by-step logical evaluation.",
 "answer": "Single uppercase letter matching your final updated choice."
}"""

    return f"""You are participating in a multi-agent debate to solve a multiple-choice exam question.
<question>{q.get('question')}
</question>
<options>{options_str}
</options>

Here are the independent solutions proposed by your fellow expert agents in Round 1:
{peers_text}
{instructions}"""


def build_judge_prompt(q, options_str, debate_transcript):
    """Builds the prompt for the Judge Model (Final Aggregation)."""
    transcript_text = ""
    for round_num, agents_data in debate_transcript.items():
        transcript_text += f"\n--- {round_num} ---\n"
        for agent_name, res in agents_data.items():
            transcript_text += f"* **{agent_name}**: Answer: **{res['answer']}** | Reasoning: {res['reasoning']}\n"

    instructions = """### Instructions
You are the lead judge reviewing a multi-agent debate between expert models on an exam question. Analyze the progression of arguments, verify factual correctness and logic across the rounds, and determine the single correct answer.
Return strictly a valid JSON object with ONLY these two keys and nothing else. Do not use markdown blocks.
{
 "reasoning": "Comprehensive adjudication synthesizing the debate and justifying the final selection.",
 "answer": "Single uppercase letter matching the final definitive correct option."
}"""

    return f"""Adjudicate the following multi-choice exam question based on the debate transcript provided.
<question>{q.get('question')}
</question>
<options>{options_str}
</options>

Debate Transcript:
{transcript_text}
{instructions}"""


def query_llm(model_name, api_key, prompt_content, base64_url, enable_thinking=False, is_debug_run=False):
    """Sends a request to the SwissAI API with retries."""
    url = "[https://api.swissai.svc.cscs.ch/v1/chat/completions](https://api.swissai.svc.cscs.ch/v1/chat/completions)"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    user_content_parts = [{"type": "text", "text": prompt_content}]
    if base64_url:
        user_content_parts.append({"type": "image_url", "image_url": {"url": base64_url}})

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": user_content_parts}],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": enable_thinking}
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    raw_content = None
    for attempt in range(3):
        try:
            enforce_rate_limit()
            with urllib.request.urlopen(req, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))
                if "choices" not in result or not result["choices"]:
                    raise ValueError(f"Unexpected API response structure: {result}")
                raw_content = result["choices"][0]["message"]["content"] or ""
                return raw_content
        except urllib.error.HTTPError as e:
            if e.code == 504 and attempt < 2:
                wait_time = 5 * (2 ** attempt)
                time.sleep(wait_time)
                continue
            if hasattr(e, 'read'):
                print(e.read().decode("utf-8"))
            raise e
        except (urllib.error.URLError, TimeoutError, socket.timeout) as ex:
            if attempt < 2:
                wait_time = 5 * (2 ** attempt)
                time.sleep(wait_time)
                continue
            raise ex
    return None


def solve_exam(exam_dir, exam_id, debater_models, judge_model, api_key, enable_thinking=False, is_debug_run=False, target_question_id=None):
    """Processes exam questions using 3 Debater models + 1 Judge model."""
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = f"llm_output/{exam_dir}/solutions_debate_{exam_id}.json"

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} (Directory: {exam_dir}) using Multi-Agent Debate ---")
    print(f"Debaters: {debater_models}")
    print(f"Judge: {judge_model}")

    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)

    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    if target_question_id:
        questions = [q for q in questions if q.get("id") == target_question_id]
        if not questions:
            print(f"Error: Question ID '{target_question_id}' not found.")
            return False

    # Resume logic
    all_answers = []
    completed_question_ids = set()
    if os.path.exists(output_json) and not target_question_id:
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                all_answers = existing_data.get("answers", [])
                completed_question_ids = {ans["id"] for ans in all_answers}
            print(f"Resuming exam: found {len(completed_question_ids)} already completed questions.")
        except Exception:
            pass

    for idx, q in enumerate(questions):
        q_id = q.get("id", f"q{idx+1}")

        if q_id in completed_question_ids and not target_question_id:
            print(f"Skipping already completed question: {q_id}")
            continue

        print(f"\nProcessing question {idx + 1}/{len(questions)} (ID: {q_id})...", flush=True)

        raw_img_path = q.get("image_path")
        img_path = resolve_and_verify_image_path(exam_dir, raw_img_path)
        base64_url = encode_image_to_base64(img_path) if img_path else None

        options_dict = q.get("options", {})
        options_str = json.dumps(options_dict, indent=2)
        valid_options = list(options_dict.keys()) if options_dict else list("ABCDEFGHIJKLMNO")

        debate_transcript = {}

        # ==========================================
        # ROUND 1: Independent Generation
        # ==========================================
        print("  -> [Round 1] Independent generation...", flush=True)
        round1_results = {}
        r1_prompt = build_round1_prompt(q, options_str, img_path if base64_url else None)

        for d_idx, model in enumerate(debater_models):
            agent_name = f"Agent_{d_idx+1}"
            try:
                raw_content = query_llm(model, api_key, r1_prompt, base64_url, enable_thinking, is_debug_run)
                reasoning, ans_value = parse_model_output(raw_content)
                if not ans_value or ans_value not in valid_options:
                    ans_value = valid_options[0]  # fallback
                round1_results[agent_name] = {"model": model, "reasoning": reasoning, "answer": ans_value}
                print(f"     - {agent_name} ({model}): Voted {ans_value}")
            except Exception as e:
                print(f"     - {agent_name} failed: {e}")
                round1_results[agent_name] = {"model": model, "reasoning": "Failed to generate.", "answer": valid_options[0]}

        debate_transcript["Round_1"] = round1_results

        # ==========================================
        # ROUND 2: Cross-Critique & Debate
        # ==========================================
        print("  -> [Round 2] Cross-critique and debate...", flush=True)
        round2_results = {}

        for d_idx, model in enumerate(debater_models):
            agent_name = f"Agent_{d_idx+1}"
            r2_prompt = build_round2_prompt(q, options_str, agent_name, round1_results)
            try:
                raw_content = query_llm(model, api_key, r2_prompt, base64_url, enable_thinking, is_debug_run)
                reasoning, ans_value = parse_model_output(raw_content)
                if not ans_value or ans_value not in valid_options:
                    ans_value = round1_results[agent_name]["answer"]  # retain previous if malformed
                round2_results[agent_name] = {"model": model, "reasoning": reasoning, "answer": ans_value}
                print(f"     - {agent_name} ({model}): Updated to {ans_value}")
            except Exception as e:
                print(f"     - {agent_name} failed in Round 2, keeping Round 1: {e}")
                round2_results[agent_name] = round1_results[agent_name]

        debate_transcript["Round_2"] = round2_results

        # ==========================================
        # ROUND 3: Judge Aggregation
        # ==========================================
        print(f"  -> [Round 3] Judge model adjudication using {judge_model}...", flush=True)
        judge_prompt = build_judge_prompt(q, options_str, debate_transcript)

        success = False
        final_answer_val = valid_options[0]
        final_reasoning = ""

        try:
            raw_content = query_llm(judge_model, api_key, judge_prompt, base64_url, enable_thinking, is_debug_run)
            reasoning, ans_value = parse_model_output(raw_content)
            if ans_value and ans_value in valid_options:
                final_answer_val = ans_value
                final_reasoning = reasoning
                success = True
            else:
                raise ValueError(f"Judge returned invalid answer: {ans_value}")
        except Exception as e:
            print(f"     - Judge failed: {e}. Falling back to majority vote from Round 2.")
            # Fallback majority vote
            ans_counts = {}
            for res in round2_results.values():
                ans_counts[res["answer"]] = ans_counts.get(res["answer"], 0) + 1
            final_answer_val = max(ans_counts, key=ans_counts.get) if ans_counts else valid_options[0]
            final_reasoning = "Judge model failed; resolved via Round 2 majority vote."
            success = True

        if success:
            parsed_answer = {
                "id": q_id,
                "debate_transcript": debate_transcript,
                "reasoning": final_reasoning,
                "answer": final_answer_val
            }
            all_answers = [ans for ans in all_answers if ans.get("id") != q_id]
            all_answers.append(parsed_answer)

            solution_data_checkpoint = {
                "examId": exam_data.get('examId', exam_id),
                "examTitle": "Signals & Systems Solutions (Multi-Agent Debate)",
                "answers": all_answers
            }
            os.makedirs(os.path.dirname(output_json), exist_ok=True)
            with open(output_json, "w", encoding="utf-8") as f_chk:
                json.dump(solution_data_checkpoint, f_chk, indent=2)
            print(f"  -> Successfully adjudicated {q_id} -> Final Answer: {final_answer_val}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an LLM exam via Multi-Agent Debate using SwissAI API.")
    parser.add_argument("--exam_dir", type=str, required=True, help="Directory name inside data/")
    parser.add_argument("--exam_id", type=str, required=True, help="Exam ID/filename suffix")
    parser.add_argument("--debater_models", type=str, required=True, help="Comma-separated list of 3 debater model names (e.g., modelA,modelB,modelC)")
    parser.add_argument("--judge_model", type=str, required=True, help="Separate judge model name")
    parser.add_argument("--api_key", type=str, default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""), help="API key")
    parser.add_argument("--enable_thinking", action="store_true", help="Enable thinking mode")
    parser.add_argument("--question_id", type=str, default=None, help="Process a single specific question ID")
    parser.add_argument("--debug", action="store_true", help="Print raw model output on failures")

    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("API key must be provided via --api_key or SWISSAI_RESEARCH_API_KEY env var.")

    debater_list = [m.strip() for m in args.debater_models.split(",")]
    if len(debater_list) != 3:
        raise ValueError("Please provide exactly 3 comma-separated debater models for Alternative A.")

    solve_exam(
        exam_dir=args.exam_dir,
        exam_id=args.exam_id,
        debater_models=debater_list,
        judge_model=args.judge_model,
        api_key=args.api_key,
        enable_thinking=args.enable_thinking,
        is_debug_run=args.debug,
        target_question_id=args.question_id
    )