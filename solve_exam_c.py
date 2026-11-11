"""
MAJORITY VOTE
"""
import os
import json
from collections import Counter
import argparse

def aggregate_ensemble(output_dir, exam_id):
    """
    Aggregates pre-computed JSON outputs from multiple models 
    to produce a majority-vote ensemble solution file.
    """
    # Define filenames for your models' pre-computed outputs
    model_files = {
        "gemma": f"{output_dir}/solutions_{exam_id}_gemma.json",
        "qwen": f"{output_dir}/solutions_{exam_id}_qwen.json",
        "deepseek": f"{output_dir}/solutions_{exam_id}_deepseek.json",
        "apertus_arbiter": f"{output_dir}/solutions_{exam_id}_apertus.json" # Pre-computed arbiter/tie-breaker outputs
    }

    # Load all available model outputs
    model_data = {}
    for name, filepath in model_files.items():
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Map answers by question ID for easy O(1) lookup
                answers_map = {ans["id"]: ans for ans in data.get("answers", [])}
                model_data[name] = answers_map
            print(f"Loaded {len(answers_map)} answers from {name} ({filepath})")
        else:
            print(f"Warning: Output file for {name} not found at {filepath}")

    if not model_data:
        print("Error: No model output files found to aggregate.")
        return

    # Identify all unique question IDs across all models
    all_question_ids = sorted(list(set(q_id for m_map in model_data.values() for q_id in m_map.keys())))
    
    ensemble_answers = []

    voting_models = [m for m in ["gemma", "qwen", "deepseek"] if m in model_data]

    for q_id in all_question_ids:
        votes = []
        model_responses_for_q = {}

        # Collect votes from voting pool models
        for model_name in voting_models:
            if q_id in model_data[model_name]:
                ans_record = model_data[model_name][q_id]
                ans_letter = ans_record.get("answer", "").strip().upper()
                if ans_letter:
                    votes.append(ans_letter)
                    model_responses_for_q[model_name] = ans_record

        if not votes:
            continue

        vote_counts = Counter(votes)
        top_answer, top_count = vote_counts.most_common(1)[0]

        # Check for a clear majority (e.g., >= 2 votes out of 3, or unanimous 2/2 tie resolution)
        # With 3 voting models, a majority means >= 2 agreeing.
        if top_count >= 2:
            # Majority consensus reached! Grab reasoning from a model that voted correctly.
            winning_record = next(r for name, r in model_responses_for_q.items() if r.get("answer", "").strip().upper() == top_answer)
            final_record = {
                "id": q_id,
                "reasoning": winning_record.get("reasoning", ""),
                "answer": top_answer,
                "consensus_type": f"majority_{top_count}_of_{len(voting_models)}"
            }
        else:
            # TIE / NO MAJORITY (e.g., 3-way split: A, B, C)
            # Fall back to pre-computed Apertus 70B arbiter if available
            if "apertus_arbiter" in model_data and q_id in model_data["apertus_arbiter"]:
                arbiter_record = model_data["apertus_arbiter"][q_id]
                final_record = {
                    "id": q_id,
                    "reasoning": arbiter_record.get("reasoning", ""),
                    "answer": arbiter_record.get("answer", "").strip().upper(),
                    "consensus_type": "arbiter_tie_breaker_precomputed"
                }
            else:
                # Absolute fallback: take the first model's answer if no arbiter file exists
                fallback_record = list(model_responses_for_q.values())[0]
                final_record = {
                    "id": q_id,
                    "reasoning": fallback_record.get("reasoning", ""),
                    "answer": fallback_record.get("answer", "").strip().upper(),
                    "consensus_type": "fallback_unanimous_split"
                }

        ensemble_answers.append(final_record)

    # Save final ensemble results
    output_filepath = f"{output_dir}/solutions_{exam_id}_ensemble_majority.json"
    ensemble_output = {
        "examId": exam_id,
        "examTitle": "Ensemble Majority Vote Solutions",
        "answers": ensemble_answers
    }

    os.makedirs(output_dir, exist_ok=True)
    with open(output_filepath, "w", encoding="utf-8") as f:
        json.dump(ensemble_output, f, indent=2)

    print(f"\nSuccess! Aggregated {len(ensemble_answers)} questions into ensemble output at '{output_filepath}'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Locally aggregate pre-computed model outputs via majority voting.")
    parser.add_argument("--output_dir", type=str, required=True, help="Directory containing the model output JSONs (e.g., llm_output/signals_exam)")
    parser.add_name = parser.add_argument("--exam_id", type=str, required=True, help="Exam ID suffix (e.g., 2026_spring)")
    
    args = parser.parse_args()
    aggregate_ensemble(args.output_dir, args.exam_id)