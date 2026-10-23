import os
import json
import urllib.request
import urllib.error

# File paths
EXAM_DIR = "signals-and-systems"
EXAM_ID = "hs21"

# Derived paths based on your variables
EXAM_FILE = f"data/{EXAM_DIR}/exam_{EXAM_ID}.json"
OUTPUT_FILE = f"llm_output/{EXAM_DIR}/output_{EXAM_ID}.json"

# Simple function to load a .env file manually
def load_env(filepath=".env"):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip("'\"")

# Load environment variables
load_env()

api_key = os.environ.get("CSCS_INFERENCE_API_KEY")
if not api_key:
    print("Error: CSCS_INFERENCE_API_KEY not found in environment or .env file.")
    exit(1)

if not os.path.exists(EXAM_FILE):
    print(f"Error: {EXAM_FILE} not found. Please ensure your exam JSON file exists.")
    exit(1)

# Load the exam file
with open(EXAM_FILE, "r", encoding="utf-8") as f:
    exam_data = json.load(f)

# Optional: Test with first few questions first
exam_data["questions"] = exam_data["questions"][:3]

# Combine system instructions and exam data into a single user message
# (to avoid gateway rejections caused by 'system' roles or unsupported parameters)
prompt_content = f"""You are an expert exam solver in Signals and Systems. You must solve the exam questions provided and output strictly valid JSON matching the requested output format. Do not include markdown code block formatting (e.g., ```json), and do not include any explanatory prose outside of the JSON object.

Please solve the following exam and select the exact correct option string for each question.

Exam Data:
{json.dumps(exam_data, indent=2)}

Return your final submission matching strictly this JSON format:
{{
  "examId": "{exam_data.get('examId', '')}",
  "answers": [
    {{ "id": "q1", "answer": "<exact option text selected>" }},
    {{ "id": "q2", "answer": "<exact option text selected>" }}
  ]
}}
"""

# API endpoint and payload (structured like your working script)
url = "[https://api.inference.cscs.ch/v1/chat/completions](https://api.inference.cscs.ch/v1/chat/completions)"
payload = {
    "model": "CSCS-Inference/google/gemma-4-31B-it",
    "messages": [
        {"role": "user", "content": prompt_content}
    ],
    "max_tokens": 1024
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

# Make the request
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="POST"
)

try:
    print("Sending exam to CSCS API...")
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        raw_content = result["choices"][0]["message"]["content"].strip()

        # Clean potential markdown backticks from response if present
        if raw_content.startswith("```"):
            lines = raw_content.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw_content = "\n".join(lines).strip()

        # Ensure output directory exists before saving
        os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

        # Parse and save the LLM output as formatted JSON
        parsed_output = json.loads(raw_content)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
            json.dump(parsed_output, f_out, indent=2)

        print(f"Success! Exam solution saved to '{OUTPUT_FILE}'.")

except urllib.error.HTTPError as e:
    print(f"HTTP Error {e.code}: {e.reason}")
    print(e.read().decode("utf-8"))
except json.JSONDecodeError:
    print("Error: The model output could not be parsed as valid JSON.")
    print("Raw output received:")
    print(raw_content)
except Exception as e:
    print("An unexpected error occurred:")
    print(e)