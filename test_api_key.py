import os
import json
import urllib.request
import urllib.error

# Simple function to load a .env file manually
def load_env(filepath=".env"):
    if not os.path.exists(filepath):
        return
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip().strip("'\"")

# Load the .env file
load_env()

api_key = os.environ.get("CSCS_INFERENCE_API_KEY")
if not api_key:
    print("Error: CSCS_INFERENCE_API_KEY not found in environment or .env file.")
    exit(1)

# API endpoint and payload
url = "https://api.inference.cscs.ch/v1/chat/completions"
payload = {
    "model": "CSCS-Inference/google/gemma-4-31B-it",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello! Reply with 'API key works!' if you can read this."}
    ],
    "max_tokens": 50
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
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode("utf-8"))
        print("Connection successful!")
        print("Response from model:")
        print(result["choices"][0]["message"]["content"])
        
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code} - {e.reason}")
    print(e.read().decode("utf-8"))
except Exception as e:
    print("An error occurred:")
    print(e)
