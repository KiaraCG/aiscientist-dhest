import os
import json
import time
import socket
import argparse
import urllib.request
import urllib.error

# Global tracker for rate limiting (max 14 calls per minute -> ~4.3 seconds interval)
_LAST_API_CALL_TIME = 0.0
MIN_API_INTERVAL = 60.0 / 14.0  # ~4.285 seconds

DEFAULT_URL = "https://api.swissai.svc.cscs.ch/v1/chat/completions"
DEFAULT_MODELS_URL = "https://api.swissai.svc.cscs.ch/v1/models"

RUN_PYTHON_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "run_python",
            "description": "Execute Python code for numerical or symbolic Signals & Systems calculations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Print final results to stdout.",
                    }
                },
                "required": ["code"],
            },
        },
    }
]

PROBE_MESSAGES = [
    {
        "role": "user",
        "content": (
            "Compute the discrete-time convolution of x[n] = [1, 2, 1] and h[n] = [1, -1] "
            "using the run_python tool before answering."
        ),
    }
]


def enforce_rate_limit():
    """Ensures at least MIN_API_INTERVAL seconds have passed since the last API call."""
    global _LAST_API_CALL_TIME
    elapsed = time.time() - _LAST_API_CALL_TIME
    if elapsed < MIN_API_INTERVAL:
        sleep_duration = MIN_API_INTERVAL - elapsed
        time.sleep(sleep_duration)
    _LAST_API_CALL_TIME = time.time()


def fetch_models(api_key, models_url=DEFAULT_MODELS_URL):
    """Fetches available model IDs from the /v1/models endpoint."""
    headers = {
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(models_url, headers=headers, method="GET")
    enforce_rate_limit()
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    model_ids = [
        item["id"] for item in data.get("data", [])
        if isinstance(item, dict) and "id" in item
    ]
    return sorted(model_ids)


def send_probe_request(url, api_key, payload, timeout=120):
    """Sends a single POST request with rate limiting and retry handling matching the harness."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    for attempt in range(3):
        try:
            enforce_rate_limit()
            with urllib.request.urlopen(req, timeout=timeout) as response:
                status = response.status
                raw_body = response.read().decode("utf-8", errors="replace")
                try:
                    return status, json.loads(raw_body)
                except json.JSONDecodeError:
                    return status, {"_raw_text": raw_body}
        except urllib.error.HTTPError as e:
            err_body = ""
            if hasattr(e, "read"):
                err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 504 and attempt < 2:
                wait_time = 5 * (2 ** attempt)
                print(f"Gateway Timeout (504). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            try:
                parsed_err = json.loads(err_body) if err_body else {}
            except json.JSONDecodeError:
                parsed_err = {"_raw_error": err_body}
            return e.code, parsed_err
        except (urllib.error.URLError, TimeoutError, socket.timeout) as ex:
            wait_time = 5 * (2 ** attempt)
            if attempt < 2:
                print(f"Timeout/Network error (Attempt {attempt + 1}/3). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            return 0, {"_network_error": str(ex)}
        except Exception as ex:
            if attempt == 2:
                return 0, {"_error": str(ex)}
            time.sleep(2)

    return 0, {"_error": "Exhausted retries"}


def extract_tool_calls(response_obj):
    """Extracts tool_calls list from a chat completions response dict if present."""
    if not isinstance(response_obj, dict):
        return []
    choices = response_obj.get("choices") or []
    if not choices:
        return []
    message = choices[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    return tool_calls if isinstance(tool_calls, list) else []


def validate_code_argument(tool_calls):
    """Checks whether the first tool call targets run_python with a valid 'code' field."""
    if not tool_calls:
        return False, None
    fn = tool_calls[0].get("function") or {}
    tool_name = fn.get("name")
    raw_args = fn.get("arguments")

    if isinstance(raw_args, dict):
        return ("code" in raw_args and isinstance(raw_args["code"], str)), tool_name
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
            return (isinstance(parsed, dict) and "code" in parsed and isinstance(parsed["code"], str)), tool_name
        except json.JSONDecodeError:
            return False, tool_name
    return False, tool_name


def probe_model(model_name, api_key, enable_thinking=False, url=DEFAULT_URL):
    """Tests whether a model supports native function/tool calling on the SwissAI endpoint."""
    record = {
        "model": model_name,
        "enable_thinking": enable_thinking,
        "supports_native_tools": False,
        "recommended_mode": "code_block",
        "attempts": {},
    }

    for tool_choice in ("auto", "required"):
        payload = {
            "model": model_name,
            "messages": PROBE_MESSAGES,
            "tools": RUN_PYTHON_TOOL,
            "tool_choice": tool_choice,
            "temperature": 0.1,
            "stream": False,
            "chat_template_kwargs": {
                "enable_thinking": enable_thinking,
            },
        }

        status, body = send_probe_request(url, api_key, payload)
        tool_calls = extract_tool_calls(body)
        valid_code, first_tool_name = validate_code_argument(tool_calls)

        error_msg = None
        if isinstance(body, dict):
            if isinstance(body.get("error"), dict):
                error_msg = body["error"].get("message")
            elif "_raw_error" in body:
                error_msg = body["_raw_error"][:300]
            elif "_network_error" in body:
                error_msg = body["_network_error"]
            elif "_error" in body:
                error_msg = body["_error"]

        record["attempts"][tool_choice] = {
            "http_status": status,
            "tool_call_count": len(tool_calls),
            "first_tool_name": first_tool_name,
            "valid_code_arg": valid_code,
            "error": error_msg,
        }

        if status == 200 and tool_calls and valid_code:
            record["supports_native_tools"] = True
            record["recommended_mode"] = "native_tools"
            break

        # If tools/tool_choice are outright rejected (400/422), skip redundant retry
        if status in (400, 422):
            break

    return record


def run_probe(model_names=None, api_key="", enable_thinking=False, output_path="model_capabilities.json"):
    if model_names:
        targets = model_names
    else:
        print(f"Fetching models from {DEFAULT_MODELS_URL}...")
        targets = fetch_models(api_key)

    if not targets:
        print("No models to test.")
        return {}

    print(f"\n--- Probing {len(targets)} model(s) for native tool support (enable_thinking={enable_thinking}) ---")
    results = {
        "endpoint": DEFAULT_URL,
        "enable_thinking": enable_thinking,
        "models": {},
    }

    for idx, model_name in enumerate(targets, start=1):
        print(f"[{idx}/{len(targets)}] Testing model: {model_name}...")
        model_res = probe_model(model_name, api_key, enable_thinking=enable_thinking)
        results["models"][model_name] = model_res
        auto_status = model_res["attempts"].get("auto", {}).get("http_status")
        print(f"    -> {model_res['recommended_mode'].upper()} (auto HTTP {auto_status})")

    out_dir = os.path.dirname(output_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nSaved capability report to '{output_path}'.")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe SwissAI models for native tool calling support.")
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Optional list of model names to test (defaults to querying /v1/models)",
    )
    parser.add_argument(
        "--api_key",
        type=str,
        default=os.environ.get("SWISSAI_RESEARCH_API_KEY", ""),
        help="API key (or set SWISSAI_RESEARCH_API_KEY env var)",
    )
    parser.add_argument(
        "--enable_thinking",
        action="store_true",
        help="Enable thinking mode in chat_template_kwargs",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="model_capabilities.json",
        help="Output JSON file path (default: model_capabilities.json)",
    )

    args = parser.parse_args()

    if not args.api_key:
        raise ValueError("API key must be provided via --api_key or the SWISSAI_RESEARCH_API_KEY environment variable.")

    run_probe(
        model_names=args.models,
        api_key=args.api_key,
        enable_thinking=args.enable_thinking,
        output_path=args.output,
    )