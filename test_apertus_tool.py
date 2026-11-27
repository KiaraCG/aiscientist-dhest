import os
import re
import sys
import json
import tempfile
import subprocess
import urllib.request

ENDPOINT = "https://api.swissai.svc.cscs.ch/v1/chat/completions"
MODEL = "CSCS-Inference/swiss-ai/Apertus-v1.5-70B"

SANDBOX_PREAMBLE = (
    "import socket as _s, warnings as _w\n"
    "def _no_net(*a, **k): raise RuntimeError('Network access is disabled in this sandbox.')\n"
    "_s.socket = _no_net; _s.create_connection = _no_net; _s.getaddrinfo = _no_net\n"
    "_w.filterwarnings('ignore')\n"
    "del _s, _w\n"
)

TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_python",
        "description": (
            "Execute Python 3 code and return what it prints (stdout) plus any error. "
            "numpy, scipy and sympy are available. No network, no internet, no figure access, "
            "no state kept between calls. Always print() the values you need."
        ),
        "parameters": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "Complete, self-contained Python code."}},
            "required": ["code"],
        },
    },
}]


def run_python(code: str, timeout: int = 20) -> str:
    with tempfile.TemporaryDirectory(prefix="sandbox_") as td:
        path = os.path.join(td, "snippet.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(SANDBOX_PREAMBLE + code)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": td,
            "TMPDIR": td,
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        proc = subprocess.run(
            [sys.executable, path], cwd=td, env=env, capture_output=True, text=True, timeout=timeout
        )
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr.strip()[-1500:]) if proc.stderr.strip() else "")
    return out.strip() or "(no output; use print() to display results)"


def call_api(api_key: str, messages: list, tool_choice: str) -> dict:
    payload = {
        "model": MODEL,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": tool_choice,
        "temperature": 0.1,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))["choices"][0]["message"]


def main():
    api_key = os.environ.get("SWISSAI_RESEARCH_API_KEY", "")
    if not api_key:
        raise SystemExit("Set SWISSAI_RESEARCH_API_KEY first.")

    # Use a non-obvious computation so you can verify the printed sandbox output in the final reply
    prompt = (
        "Compute discrete-time convolution of x=[1, 2, 1] and h=[1, -1] using run_python "
        "and print a unique verification token like TOKEN_94827 alongside the result, then answer."
    )
    messages = [{"role": "user", "content": prompt}]

    # Turn 1: force run_python
    msg1 = call_api(api_key, messages, tool_choice="required")
    tool_calls = msg1.get("tool_calls") or []
    print("Turn 1 tool_calls count:", len(tool_calls))
    assert tool_calls, f"Expected tool_calls, got content: {msg1.get('content')}"

    messages.append({
        "role": "assistant",
        "content": msg1.get("content") or "",
        "tool_calls": tool_calls,
    })

    for tc in tool_calls:
        args = json.loads(tc["function"]["arguments"])
        code = args["code"]
        print("\n--- Code executed in your sandbox ---\n" + code)
        output = run_python(code)
        print("\n--- Sandbox stdout/stderr ---\n" + output)
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output})

    # Turn 2: allow final text answer without further tool calls
    msg2 = call_api(api_key, messages, tool_choice="none")
    print("\n--- Final model response ---\n" + (msg2.get("content") or ""))


if __name__ == "__main__":
    main()