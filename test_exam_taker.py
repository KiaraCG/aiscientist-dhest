import os
import json
import urllib.request
import urllib.error

# File paths
EXAM_DIR = "signals-and-systems"
EXAM_ID = "hs21"
EXAM_FILE = f"data/{EXAM_DIR}/exam_{EXAM_ID}.json"


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


load_env()
api_key = os.environ.get("CSCS_INFERENCE_API_KEY")

if not api_key:
    print("Error: CSCS_INFERENCE_API_KEY not found.")
    exit(1)

if not os.path.exists(EXAM_FILE):
    print(f"Error: {EXAM_FILE} not found.")
    exit(1)

# Load just the first question for a lightweight test
with open(EXAM_FILE, "r", encoding="utf-8") as f:
    exam_data = json.load(f)
exam_data["questions"] = exam_data["questions"][:1]

url = "https://api.inference.cscs.ch/v1/chat/completions"
payload = {
    "model": "CSCS-Inference/google/gemma-4-31B-it",
    "messages": [
        {"role": "user", "content": f"Solve this exam question and output valid JSON: {json.dumps(exam_data)}"}
    ],
    "max_tokens": 150
}

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {api_key}"
}

req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers=headers,
    method="POST"
)

try:
    print("Sending diagnostic request to CSCS API...")
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        print("Success!")
        print(result["choices"][0]["message"]["content"])

except urllib.error.HTTPError as e:
    print(f"\nHTTP Error {e.code}: {e.reason}")
    error_details = e.read().decode("utf-8")
    print(f"Server Error Response Body:\n{error_details}")
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")