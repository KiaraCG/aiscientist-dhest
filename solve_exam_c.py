#!/usr/bin/env python3
"""
Variant C: self-consistency (B + k samples + majority vote).

For each question, draw k independent reasoning samples and return the most common final answer.
Sample 0 is run at the low base temperature (--temperature, default 0.1) and acts as the tie-breaker;
samples 1..k-1 run at --sample-temperature (default 0.7).

Cost is ~k x variant B. Concurrency = --workers (questions) x --sample-workers (samples per question),
so lower --workers if you hit 429s.

Requires solve_exam_b.py in the same directory.
Example:  python solve_exam_c.py --examid hs17 --k 5
"""
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from solve_exam_b import LLMError, make_result, run_cli, sample_once


def add_args(p):
    p.add_argument("--k", type=int, default=5, help="Samples per question.")
    p.add_argument("--sample-temperature", type=float, default=0.7)
    p.add_argument("--sample-workers", type=int, default=3, help="Concurrent samples per question.")


def solve_question_c(nq, args, api_key):
    temps = [args.temperature] + [args.sample_temperature] * max(0, args.k - 1)

    def one(t):
        try:
            return sample_once(nq, args, api_key, temperature=t)
        except Exception as e:  # a single bad sample must not sink the question
            return {"choice": None, "reasoning": "", "error": f"{type(e).__name__}: {e}"}

    with ThreadPoolExecutor(max_workers=max(1, args.sample_workers)) as ex:
        samples = list(ex.map(one, temps))  # order preserved: samples[0] is the low-temp one

    valid = [s for s in samples if s.get("choice")]
    if not valid:
        errs = "; ".join(s.get("error", "no parsable answer") for s in samples)[:500]
        raise LLMError(f"all {len(samples)} samples failed: {errs}")

    key = (lambda c: c) if nq["options"] else (lambda c: c.strip().lower())
    votes = Counter(key(s["choice"]) for s in valid)
    top = max(votes.values())
    tied = {c for c, v in votes.items() if v == top}
    winner_sample = next(s for s in valid if key(s["choice"]) in tied)  # earliest valid sample wins ties
    winner = winner_sample["choice"]

    return make_result(
        nq, winner, winner_sample["reasoning"],
        votes=dict(votes), samples_valid=len(valid), samples_total=len(samples),
        agreement=round(top / len(valid), 3),
        all_choices=[s.get("choice") for s in samples],
    )


if __name__ == "__main__":
    sys.exit(run_cli(
        solve_question_c,
        lambda a: f"C_k{a.k}_t{a.sample_temperature}",
        add_args=add_args,
        description="Variant C: self-consistency with majority vote.",
    ))