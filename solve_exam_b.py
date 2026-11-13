"""
REASON-THEN-ANSWER
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
        sleep_duration = MIN_API_INTERVAL - elapsed
        time.sleep(sleep_duration)
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
    
    # Check direct path first
    if os.path.exists(img_path):
        return img_path
    
    # Check relative to the exam data directory (e.g., data/exam_dir/img_path)
    candidate = os.path.join("data", exam_dir, img_path)
    if os.path.exists(candidate):
        return candidate
        
    print(f"Warning: Image path specified ('{img_path}') but file does not exist on disk. Proceeding as text-only.")
    return None

def extract_json_safely(raw_content):
    """Safely extract JSON from raw model output, cleaning up markdown and rogue list artifacts."""
    content = raw_content.strip()
    
    # Strip markdown code blocks
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
            cleaned_json_str = match.group(0)
            return json.loads(cleaned_json_str)
        raise e

def solve_exam(exam_dir, exam_id, model_name, api_key, enable_thinking=False, is_debug_run=False, target_question_id=None):
    """Processes a single exam file question-by-question using Reason-then-Answer, queries the LLM, saves JSON."""
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = f"llm_output/{exam_dir}/solutions_{exam_id}.json"
    output_pdf = f"llm_output/{exam_dir}/output_{exam_id}.pdf"

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} (Directory: {exam_dir}) using model: {model_name} (Reason-Then-Answer Harness, Thinking: {enable_thinking}) ---")

    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)

    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    # Filter to a single question if target_question_id is specified
    if target_question_id:
        questions = [q for q in questions if q.get("id") == target_question_id]
        if not questions:
            print(f"Error: Question ID '{target_question_id}' not found in exam data.")
            return False
        print(f"--> Isolation Mode Enabled: Testing ONLY Question ID: {target_question_id}")

    # Load already completed answers if solutions file exists (resume logic)
    all_answers = []
    completed_question_ids = set()
    if os.path.exists(output_json) and not target_question_id:
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                all_answers = existing_data.get("answers", [])
                completed_question_ids = {ans["id"] for ans in all_answers}
            print(f"Resuming exam: found {len(completed_question_ids)} already answered questions.")
        except Exception:
            pass

    url = "https://api.swissai.svc.cscs.ch/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    print(f"Starting processing of {len(questions)} target question(s)...")

    for idx, q in enumerate(questions):
        q_id = q.get("id", f"q{idx+1}")
        
        # Skip if already answered in a previous partial run (unless targeting single question)
        if q_id in completed_question_ids and not target_question_id:
            print(f"Skipping already completed question: {q_id}")
            continue

        print(f"Processing question {idx + 1}/{len(questions)} (ID: {q_id})...", flush=True)

        raw_img_path = q.get("image_path")
        img_path = resolve_and_verify_image_path(exam_dir, raw_img_path)
        
        if img_path:
            if is_debug_run:
                print(f"  -> Encoding image to base64: {img_path}", flush=True)
            base64_url = encode_image_to_base64(img_path)
            if is_debug_run:
                print(f"  -> Image encoded successfully.", flush=True)
        else:
            base64_url = None

        options_str = json.dumps(q.get("options", {}), indent=2)

        user_content_parts = []

        if base64_url and "images_merged" in img_path:
            prompt_content = f"""Solve this multiple-choice exam question using a reason-then-answer approach.
Question ID: {q_id}
Question Text: {q.get('question')}
Note: The main question figure and options [A], [B], [C], and [D] are fully visible in the attached image.

Return strictly a JSON object with ONLY these two keys, and nothing else:
{{
  "id": "{q_id}",
  "reasoning": "<Step-by-step analysis, and choices derivation>",
  "answer": "<Single letter. Must be one of: A, B, C, D, E, F, G, H, I, J, K, L, M, N, or O>"
}}
"""
            user_content_parts.append({"type": "text", "text": prompt_content})
            user_content_parts.append({"type": "image_url", "image_url": {"url": base64_url}})

        elif base64_url and "images_task_only" in img_path:
            prompt_content = f"""Solve this multiple-choice exam question using a reason-then-answer approach.
Question ID: {q_id}
Question Text: {q.get('question')}
Options:
{options_str}

CRITICAL: You must choose the option letter (A, B, C, D, E, or F) that matches the correct approximation. Do NOT output raw mathematical values (like numbers, angles, or expressions) in the 'answer' field.

Return strictly a JSON object with ONLY these two keys, and nothing else:
{{
  "id": "{q_id}",
  "reasoning": "<Step-by-step analysis and derivation>",
  "answer": "<A single capital letter corresponding to the correct option: A, B, C, D, E, or F>"
}}
"""
            user_content_parts.append({"type": "text", "text": prompt_content})
            user_content_parts.append({"type": "image_url", "image_url": {"url": base64_url}})

        else:
            prompt_content = f"""Solve this multiple-choice exam question using a reason-then-answer approach.
Question ID: {q_id}
Question Text: {q.get('question')}
Options:
{options_str}

Return strictly a JSON object with ONLY these two keys, and nothing else:
{{
  "id": "{q_id}",
  "reasoning": "<Detailed logical reasoning step-by-step>",
  "answer": "<Single letter. Must be one of: A, B, C, D, E, F, G, H, I, J, K, L, M, N, or O>"
}}
"""
            user_content_parts.append({"type": "text", "text": prompt_content})

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise automated exam solver. First perform your step-by-step reasoning, then output valid raw JSON containing both 'reasoning' and 'answer' fields without markdown or external explanations."
                },
                {
                    "role": "user",
                    "content": user_content_parts
                }
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": enable_thinking
            }
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        success = False
        for attempt in range(3):
            try:
                enforce_rate_limit()

                print(f"  -> Sending request for {q_id} (Attempt {attempt + 1}/3)...", flush=True)
                with urllib.request.urlopen(req, timeout=180) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    
                    # Guard against unexpected API response structures
                    if "choices" not in result or not result["choices"]:
                        raise ValueError(f"Unexpected API response structure: {result}")
                        
                    raw_content = result["choices"][0]["message"]["content"]
                    parsed_answer = extract_json_safely(raw_content)
                    
                    parsed_answer = extract_json_safely(raw_content)

                    if not parsed_answer or "answer" not in parsed_answer:
                        raise ValueError(f"Extracted JSON missing 'answer' key or failed to parse. Raw content: {raw_content}")

                    ans_value = str(parsed_answer["answer"]).strip().upper()
                    valid_options = list(q.get("options", {}).keys()) # e.g., ['A', 'B', 'C', 'D', 'E', 'F']
                    if ans_value not in valid_options:
                        raise ValueError(f"Model returned invalid answer '{ans_value}' for {q_id}. Expected one of {valid_options}.")

                    # --- SUCCESS PATH ---
                    parsed_answer["id"] = q_id
                    # Replace if already exists in list (for single-question re-runs)
                    all_answers = [ans for ans in all_answers if ans.get("id") != q_id]
                    all_answers.append(parsed_answer)
                    
                    solution_data_checkpoint = {
                        "examId": exam_data.get('examId', exam_id),
                        "examTitle": "Signals & Systems Solutions (Reason-Then-Answer)",
                        "answers": all_answers
                    }
                    os.makedirs(os.path.dirname(output_json), exist_ok=True)
                    with open(output_json, "w", encoding="utf-8") as f_chk:
                        json.dump(solution_data_checkpoint, f_chk, indent=2)

                    success = True
                    print(f"  -> Successfully processed {q_id}!")
                    break

            except urllib.error.HTTPError as e:
                if e.code == 504 and attempt < 2:
                    wait_time = 5 * (2 ** attempt)
                    print(f"Gateway Timeout (504) on question {q_id}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"HTTP Error {e.code}: {e.reason}")
                if hasattr(e, 'read'):
                    print(e.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, socket.timeout) as ex:
                wait_time = 5 * (2 ** attempt)
                if attempt < 2:
                    print(f"Timeout/Network error on question {q_id} (Attempt {attempt + 1}/3). Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                print(f"Attempt {attempt + 1} failed for question {q_id}: {ex}")
                break
            except Exception as ex:
                print(f"Attempt {attempt + 1} failed for question {q_id}: {ex}")
                if is_debug_run and 'raw_content' in locals():
                    print("\n--- RAW MODEL OUTPUT START ---")
                    print(raw_content)
                    print("--- RAW MODEL OUTPUT END ---\n")
                if attempt == 2:
                    break
                time.sleep(2)

        if not success:
            print(f"Warning: Question {q_id} failed after retries.")

    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an LLM on exam questions via SwissAI API using Reason-Then-Answer harness.")
    parser.add_argument("--exam_dir", type=str, required=True, help="Directory name inside data/ (e.g., signals_exam)")
    parser.add_argument("--exam_id", type=str, required=True, help="Exam ID/filename suffix (e.g., 2026_spring)")
    parser.add_argument("--model_name", type=str, required=True, help="Model name to query (e.g., meta-llama/Llama-3.1-70B-Instruct)")
    parser.add_argument("--api_key", type=str, default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""), help="API key")
    parser.add_argument("--enable_thinking", action="store_true", help="Enable thinking mode")
    parser.add_argument("--question_id", type=str, default=None, help="Process a single specific question ID (e.g., q12)")

    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("API key must be provided via --api_key or the SWISSAI_RESEARCH_API_KEY environment variable.")

    solve_exam(
        exam_dir=args.exam_dir,
        exam_id=args.exam_id,
        model_name=args.model_name,
        api_key=args.api_key,
        enable_thinking=args.enable_thinking,
        is_debug_run=False,
        target_question_id=args.question_id
    )