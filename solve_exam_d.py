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

# Global tracker for rate limiting (max 14 calls per minute -> ~4.3 seconds interval)
_LAST_API_CALL_TIME = 0.0
MIN_API_INTERVAL = 60.0 / 14.0

def enforce_rate_limit():
    global _LAST_API_CALL_TIME
    elapsed = time.time() - _LAST_API_CALL_TIME
    if elapsed < MIN_API_INTERVAL:
        time.sleep(MIN_API_INTERVAL - elapsed)
    _LAST_API_CALL_TIME = time.time()

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
    return None

def extract_json_safely(raw_content):
    content = raw_content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return json.loads(content.strip())

def call_llm(url, headers, model_name, messages, enable_thinking=False, temperature=0.2):
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": enable_thinking}
    }
    for attempt in range(3):
        try:
            enforce_rate_limit()
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"]
        except Exception as ex:
            if attempt < 2:
                time.sleep(5 * (2 ** attempt))
                continue
            print(f"API call failed for {model_name}: {ex}")
    return None

def solve_exam(exam_dir, exam_id, api_key, enable_thinking=False, is_debug_run=False):
    # Mapping your 4 models to roles
    MODEL_A = "CSCS-Inference/google/gemma-4-31B-it"
    MODEL_B = "SwissAI-Research/Qwen/Qwen3.8-27B"
    ARBITER = "Apertus-v1.5-70B"

    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = f"llm_output/{exam_dir}/solutions_{exam_id}_debate.json"

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} using Peer Debate Harness ---")
    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)

    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    all_answers = []
    completed_question_ids = set()
    if os.path.exists(output_json):
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                all_answers = existing_data.get("answers", [])
                completed_question_ids = {ans["id"] for ans in all_answers}
        except Exception:
            pass

    url = "[https://api.swissai.svc.cscs.ch/v1/chat/completions](https://api.swissai.svc.cscs.ch/v1/chat/completions)"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

    for idx, q in enumerate(questions):
        q_id = q.get("id", f"q{idx+1}")
        if q_id in completed_question_ids:
            continue

        print(f"Processing question {idx + 1}/{len(questions)} (ID: {q_id})...")

        img_path = resolve_and_verify_image_path(exam_dir, q.get("image_path"))
        base64_url = encode_image_to_base64(img_path) if img_path else None
        options_str = json.dumps(q.get("options", {}), indent=2)

        base_prompt = f"Question ID: {q_id}\nQuestion Text: {q.get('question')}\nOptions:\n{options_str}"
        user_content_parts = [{"type": "text", "text": base_prompt}]
        if base64_url:
            user_content_parts.append({"type": "image_url", "image_url": {"url": base64_url}})

        # --- ROUND 1: Independent Proposals ---
        ans_a = call_llm(url, headers, MODEL_A, [{"role": "system", "content": "Provide your step-by-step reasoning and final answer option."}, {"role": "user", "content": user_content_parts}], enable_thinking)
        ans_b = call_llm(url, headers, MODEL_B, [{"role": "system", "content": "Provide your step-by-step reasoning and final answer option."}, {"role": "user", "content": user_content_parts}], enable_thinking)

        # --- ROUND 2: Peer Review / Revisions ---
        review_prompt_a = user_content_parts + [
            {"type": "text", "text": f"Here is another model's proposed solution and reasoning:\n{ans_b}\n\nReview their logic, point out any flaws, and state your final updated reasoning and answer."}
        ]
        review_prompt_b = user_content_parts + [
            {"type": "text", "text": f"Here is another model's proposed solution and reasoning:\n{ans_a}\n\nReview their logic, point out any flaws, and state your final updated reasoning and answer."}
        ]

        final_a = call_llm(url, headers, MODEL_A, [{"role": "user", "content": review_prompt_a}], enable_thinking)
        final_b = call_llm(url, headers, MODEL_B, [{"role": "user", "content": review_prompt_b}], enable_thinking)

        # --- ROUND 3: Arbiter Judgment ---
        transcript = f"=== Model A Final Position ===\n{final_a}\n\n=== Model B Final Position ===\n{final_b}"
        arbiter_prompt = f"Review the debate transcript for Question {q_id} below and determine the correct answer.\n\n{transcript}\n\nReturn strictly valid JSON with ONLY these two keys:\n{{\n  \"id\": \"{q_id}\",\n  \"reasoning\": \"<Synthesized justification>\",\n  \"answer\": \"<Single letter option>\"\n}}"

        raw_arbiter = call_llm(url, headers, ARBITER, [{"role": "system", "content": "You are an objective judge. Output strictly raw JSON without markdown."}, {"role": "user", "content": arbiter_prompt}], enable_thinking=False, temperature=0.0)

        try:
            parsed_answer = extract_json_safely(raw_arbiter)
            if parsed_answer and "answer" in parsed_answer:
                parsed_answer["id"] = q_id
                all_answers.append(parsed_answer)
                os.makedirs(os.path.dirname(output_json), exist_ok=True)
                with open(output_json, "w", encoding="utf-8") as f_chk:
                    json.dump({"examId": exam_data.get('examId', exam_id), "answers": all_answers}, f_chk, indent=2)
        except Exception as ex:
            print(f"Failed parsing arbiter for {q_id}: {ex}")

    print(f"Completed! Solutions saved to '{output_json}'.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--exam_dir", type=str, required=True)
    parser.add_argument("--exam_id", type=str, required=True)
    parser.add_argument("--api_key", type=str, default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""))
    parser.add_argument("--enable_thinking", action="store_true")
    args = parser.parse_args()

    solve_exam(exam_dir=args.exam_dir, exam_id=args.exam_id, api_key=args.api_key, enable_thinking=args.enable_thinking, is_debug_run=True)