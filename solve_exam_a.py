import os
import json
import time
import socket
import base64
import argparse
import urllib.request
import urllib.error

def encode_image_to_base64(image_path):
    """Encodes a local image file into a base64 data URL."""
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")
            ext = image_path.split('.')[-1].lower()
            mime = f"image/{ext}" if ext in ['png', 'jpg', 'jpeg', 'gif', 'webp'] else "image/png"
            return f"data:{mime};base64,{encoded}"
    return None

def extract_json_safely(raw_content):
    """Safely extract JSON from raw model output, handling potential markdown code blocks."""
    content = raw_content.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    return json.loads(content)

def solve_exam(exam_dir, exam_id, model_name, api_key):
    """Processes a single exam file question-by-question, queries the LLM, saves JSON, and generates a PDF."""
    exam_file = f"data/{exam_dir}/{exam_id}.json"
    output_json = f"llm_output/{exam_dir}/solutions_{exam_id}.json"
    output_pdf = f"llm_output/{exam_dir}/output_{exam_id}.pdf"

    if not os.path.exists(exam_file):
        print(f"Error: {exam_file} not found.")
        return False

    print(f"\n--- Processing Exam ID: {exam_id} (Directory: {exam_dir}) using model: {model_name} (1 call per question) ---")

    with open(exam_file, "r", encoding="utf-8") as f:
        exam_data = json.load(f)

    questions = exam_data.get('questions', [])
    if not questions and isinstance(exam_data, list):
        questions = exam_data

    # Load already completed answers if solutions file exists (resume logic)
    all_answers = []
    completed_question_ids = set()
    if os.path.exists(output_json):
        try:
            with open(output_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
                all_answers = existing_data.get("answers", [])
                completed_question_ids = {ans["id"] for ans in all_answers}
            print(f"Resuming exam: found {len(completed_question_ids)} already answered questions.")
        except Exception:
            pass

    url = "[https://api.swissai.svc.cscs.ch/v1/chat/completions](https://api.swissai.svc.cscs.ch/v1/chat/completions)"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }

    print(f"Starting processing of {len(questions)} total questions...")

    for idx, q in enumerate(questions):
        q_id = q.get("id", f"q{idx+1}")
        
        # Skip if already answered in a previous partial run
        if q_id in completed_question_ids:
            print(f"Skipping already completed question: {q_id}")
            continue

        print(f"Processing question {idx + 1}/{len(questions)} (ID: {q_id})...")

        prompt_content = f"""You are an expert exam solver in Signals and Systems. Solve the provided exam question and return strictly valid JSON matching the exact requested format. Do not include markdown code blocks or explanatory prose outside the JSON.
        
        Exam Question Data:
        {json.dumps(q, indent=2)}

        Return strictly this JSON format:
        {{
        "id": "{q_id}",
        "question": "<short description/summary of question>",
        "answer": "<exact option text selected>",
        "explanation": "<concise step-by-step solution logic>"
        }}
        """

        user_content_parts = [
            {
                "type": "text",
                "text": prompt_content
            }
        ]

        img_path = q.get("image_path")
        base64_url = encode_image_to_base64(img_path)
        if base64_url:
            user_content_parts.append({
                "type": "image_url",
                "image_url": {
                    "url": base64_url
                }
            })

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise automated exam solver. Output ONLY valid raw JSON without markdown or explanations outside the JSON object."
                },
                {
                    "role": "user",
                    "content": user_content_parts
                }
            ],
            "temperature": 0.1,
            "stream": False
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
                with urllib.request.urlopen(req, timeout=120) as response:
                    result = json.loads(response.read().decode("utf-8"))
                    raw_content = result["choices"][0]["message"]["content"]
                    parsed_answer = extract_json_safely(raw_content)
                    
                    if parsed_answer and "answer" in parsed_answer:
                        parsed_answer["id"] = q_id
                        all_answers.append(parsed_answer)
                        
                        # Incremental checkpoint save
                        solution_data_checkpoint = {
                            "examId": exam_data.get('examId', exam_id),
                            "examTitle": "Signals & Systems Solutions",
                            "answers": all_answers
                        }
                        os.makedirs(os.path.dirname(output_json), exist_ok=True)
                        with open(output_json, "w", encoding="utf-8") as f_chk:
                            json.dump(solution_data_checkpoint, f_chk, indent=2)

                    success = True
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
                if attempt == 2:
                    break
                time.sleep(2)

        if not success:
            print(f"Warning: Question {q_id} failed after retries. Continuing to next question...")
        
        time.sleep(0.5)

    solution_data = {
        "examId": exam_data.get('examId', exam_id),
        "examTitle": "Signals & Systems Solutions",
        "answers": all_answers
    }

    os.makedirs(os.path.dirname(output_json), exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(solution_data, f, indent=2)
    print(f"Final JSON saved to '{output_json}'.")

    if 'generate_compact_pdf' in globals():
        generate_compact_pdf(solution_data, output_pdf, exam_id)
        print(f"Success! Exam solution PDF saved to '{output_pdf}'.")
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate an LLM on exam questions via SwissAI API.")
    parser.add_argument("--exam_dir", type=str, required=True, help="Directory name inside data/ (e.g., signals_exam)")
    parser.add_argument("--exam_id", type=str, required=True, help="Exam ID/filename suffix (e.g., 2026_spring)")
    parser.add_argument("--model_name", type=str, required=True, help="Model name to query (e.g., meta-llama/Llama-3.1-70B-Instruct)")
    parser.add_argument("--api_key", type=str, default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""), help="API key (or set SWISSAI_RESEARCH_API_KEY env var)")

    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("API key must be provided via --api_key or the SWISSAI_RESEARCH_API_KEY environment variable.")

    solve_exam(
        exam_dir=args.exam_dir,
        exam_id=args.exam_id,
        model_name=args.model_name,
        api_key=args.api_key
    )