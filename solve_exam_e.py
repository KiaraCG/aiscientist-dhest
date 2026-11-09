#!/usr/bin/env python3
"""
Variant E: tool-augmented solving (B + executable Python).

The model may write one ```python block per turn (numpy / scipy / sympy). The harness runs it in a
subprocess, feeds back stdout/stderr, and repeats for up to --max-rounds turns. When the model emits
no code block it must finish with `FINAL: <letter>`. If the tool budget runs out, a final answer is forced.

Anything the model writes after a code block is discarded (the model can't know the output yet),
so hallucinated "outputs" never reach the transcript.

SAFETY: model-written code runs locally. The subprocess gets a temp working dir, a CPU-time + memory
limit (POSIX only), a wall-clock timeout, and an environment with KEY/TOKEN/SECRET variables removed.
This is NOT a real sandbox. For untrusted or shared machines, run the whole script inside a container.

Requires solve_exam_b.py in the same directory, plus:  pip install numpy scipy sympy
Example:  python solve_exam_e.py --examid hs17 --max-rounds 4
"""
import os
import re
import subprocess
import sys
import tempfile

from solve_exam_b import (LLMError, build_messages, call_llm, fallback_extract, make_result,
                          parse_final, run_cli)

SYSTEM_E = (
    "You are an expert in Signals and Systems solving exam questions. You can run Python "
    "(numpy, scipy, sympy are installed). To run code, write exactly ONE fenced block starting with "
    "```python, use print() for results, and then STOP and wait: you will receive the output in the next message. "
    "Use code for numerical or symbolic work (convolutions, Fourier/Laplace/z-transforms, poles and zeros, "
    "sampling/aliasing, difference equations, integrals) and verify candidate options numerically when possible. "
    "Do conceptual reasoning yourself. When you are done, do NOT write a code block; give a short justification "
    "and end with a line `FINAL: <letter>`."
)
CODE_RE = re.compile(r"```(?:python|py)[ \t]*\n(.*?)```", re.DOTALL)

PREAMBLE = """\
try:
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, ({cpu}, {cpu}))
    resource.setrlimit(resource.RLIMIT_AS, (4 << 30, 4 << 30))
except Exception:
    pass
import warnings
warnings.filterwarnings("ignore")
"""


def run_python(code, timeout=20, max_chars=2000):
    env = {k: v for k, v in os.environ.items()
           if not any(s in k.upper() for s in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update({"MPLBACKEND": "Agg", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "snippet.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(PREAMBLE.format(cpu=timeout) + "\n" + code)
        try:
            p = subprocess.run([sys.executable, path], cwd=d, env=env, capture_output=True, text=True,
                               timeout=timeout + 5, stdin=subprocess.DEVNULL)
            out = p.stdout
            if p.returncode != 0:
                out += "\n[stderr]\n" + p.stderr[-800:]
        except subprocess.TimeoutExpired:
            out = f"[error] code timed out after {timeout}s"
    out = out.strip() or "(no output; did you forget print()?)"
    return out if len(out) <= max_chars else out[:max_chars] + "\n...[output truncated]"


def solve_question_e(nq, args, api_key):
    messages = build_messages(nq, system=SYSTEM_E)
    trace = []
    text = ""
    for rnd in range(args.max_rounds + 1):
        force = rnd == args.max_rounds
        if force:
            messages.append({"role": "user", "content":
                             "Tool budget used up. Do not write code. Give your final answer now, "
                             "ending with `FINAL: <letter>`."})
        text = call_llm(messages, args.model, api_key, temperature=args.temperature,
                        max_tokens=args.max_tokens, idle_timeout=args.idle_timeout)
        m = None if force else CODE_RE.search(text)
        if not m:
            break
        code = m.group(1)
        output = run_python(code, timeout=args.code_timeout)
        trace.append({"round": rnd + 1, "code": code, "output": output})
        messages.append({"role": "assistant", "content": text[:m.end()]})  # drop hallucinated continuation
        messages.append({"role": "user", "content":
                         f"Output:\n```\n{output}\n```\nContinue. Run more code if needed; "
                         f"otherwise finish with `FINAL: <letter>` and no code block."})

    choice = parse_final(text, nq)
    used_fallback = False
    if choice is None:
        transcript = "\n\n".join(f"[code]\n{t['code']}\n[output]\n{t['output']}" for t in trace) + "\n\n" + text
        choice, used_fallback = fallback_extract(transcript, nq, args, api_key), True
    return make_result(nq, choice, f"[tool calls: {len(trace)}]\n{text}",
                       tool_calls=len(trace), trace=trace, used_fallback=used_fallback)


def add_args(p):
    p.add_argument("--max-rounds", type=int, default=4, help="Max code executions per question.")
    p.add_argument("--code-timeout", type=int, default=20, help="Seconds per code execution.")


def preflight():
    out = run_python("import numpy, scipy, sympy; print('ok')", timeout=60)
    if out.strip() != "ok":
        print("WARNING: numpy/scipy/sympy are not importable by this Python; tool calls will mostly fail.\n"
              f"  {out[:300]}\n  Fix with: pip install numpy scipy sympy")


if __name__ == "__main__":
    preflight()
    sys.exit(run_cli(
        solve_question_e,
        lambda a: f"E_r{a.max_rounds}",
        add_args=add_args,
        description="Variant E: tool-augmented (python execution) solving.",
    ))