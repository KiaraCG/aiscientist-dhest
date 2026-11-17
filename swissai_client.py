"""Shared helpers for the free-text solver and grader (SwissAI chat-completions API)."""
import os
import re
import json
import time
import socket
import base64
import urllib.request
import urllib.error

API_URL = "https://api.swissai.svc.cscs.ch/v1/chat/completions"
MIN_API_INTERVAL = 60.0 / 14.0  # max 14 calls per minute
_LAST_API_CALL_TIME = 0.0


def enforce_rate_limit():
    global _LAST_API_CALL_TIME
    elapsed = time.time() - _LAST_API_CALL_TIME
    if elapsed < MIN_API_INTERVAL:
        time.sleep(MIN_API_INTERVAL - elapsed)
    _LAST_API_CALL_TIME = time.time()


def encode_image_to_base64(image_path):
    if image_path and os.path.exists(image_path):
        with open(image_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        ext = image_path.split(".")[-1].lower()
        mime = f"image/{ext}" if ext in ["png", "jpg", "jpeg", "gif", "webp"] else "image/png"
        return f"data:{mime};base64,{encoded}"
    return None


def resolve_image_path(exam_dir, img_path):
    """Return a path that exists on disk, or None (with a warning) so the run continues text-only."""
    if not img_path:
        return None
    if os.path.exists(img_path):
        return img_path
    candidate = os.path.join("data", exam_dir, img_path)
    if os.path.exists(candidate):
        return candidate
    print(f"Warning: image '{img_path}' not found on disk. Proceeding without it.")
    return None


def split_think(content):
    """Separate a <think>...</think> block from the visible answer."""
    m = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    think = m.group(1).strip() if m else None
    rest = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    return think, rest


def extract_json_safely(raw):
    content = raw.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def call_llm(model_name, api_key, messages, temperature=0.1, enable_thinking=False,
             json_mode=False, timeout=300, max_attempts=3):
    """POST one chat completion with retry/backoff on gateway and network errors. Returns the content string."""
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    last_err = None
    for attempt in range(max_attempts):
        try:
            enforce_rate_limit()
            req = urllib.request.Request(API_URL, data=json.dumps(payload).encode("utf-8"),
                                         headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            if "choices" not in result or not result["choices"]:
                raise ValueError(f"Unexpected API response: {result}")
            return result["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            last_err = e
            body = e.read().decode("utf-8") if hasattr(e, "read") else ""
            if e.code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                wait = 5 * (2 ** attempt)
                print(f"  HTTP {e.code}; retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.reason} {body}")
        except (urllib.error.URLError, TimeoutError, socket.timeout) as e:
            last_err = e
            if attempt < max_attempts - 1:
                wait = 5 * (2 ** attempt)
                print(f"  Network/timeout error ({e}); retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Network error: {e}")
    raise RuntimeError(f"Failed after {max_attempts} attempts: {last_err}")
