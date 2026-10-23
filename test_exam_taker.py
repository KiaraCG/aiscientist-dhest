import os
import json
import urllib.request
import urllib.error


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

url = "https://api.inference.cscs.ch/v1/chat/completions"
payload = {
    "model": "CSCS-Inference/google/gemma-4-31B-it",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Output a valid JSON object with a single key 'status' and value 'ok'."}
    ],
    "max_tokens": 50
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
    print("Sending neutral request to CSCS API...")
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        print("Success!")
        print(result["choices"][0]["message"]["content"])

except urllib.error.HTTPError as e:
    print(f"\nHTTP Error {e.code}: {e.reason}")
    print(e.read().decode("utf-8"))
except Exception as e:
    print(f"\nAn unexpected error occurred: {e}")