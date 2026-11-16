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
        "gemma": f"{output_dir}/Gemma-4/solutions_{exam_id}.json",
        "qwen": f"{output_dir}/Qwen3.8-27B/solutions_{exam_id}.json",
        "deepseek": f"{output_dir}/DeepSeek/solutions_{exam_id}.json",
        "apertus": f"{output_dir}/Apertus-v1.5-70B/solutions_{exam_id}.json" 
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

    voting_models = [m for m in ["gemma", "qwen", "deepseek", "apertus"] if m in model_data]

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

        vote_counter = Counter(votes)
        vote_counts = vote_counter.most_common(len(voting_models))
        top_answer, top_count = vote_counts[0]
        second_top_cnt = vote_counts[1][1] if len(vote_counts) > 1 else 0

        # Check for a clear majority (e.g., >= 2 votes out of 3, or unanimous 2/2 tie resolution)
        # With 3 voting models, a majority means >= 2 agreeing.
        if top_count >= 2 and second_top_cnt != top_count:
            winning_record = next(r for name, r in model_responses_for_q.items() if r.get("answer", "").strip().upper() == top_answer)
            final_record = {
                "id": q_id,
                "answer": top_answer,
                "consensus_type": f"majority_{top_count}_of_{len(voting_models)}"
            }
        else:
            final_record = {
                "id": q_id,
                "answer": "NO_MAJORITY",
                "consensus_type": dict(vote_counts)
            }

        ensemble_answers.append(final_record)

    # Save final ensemble results
    output_filepath = f"processed-data/majority-vote-reason-then-answer/solutions_{exam_id}.json"
    ensemble_output = {
        "examId": exam_id,
        "examTitle": "Signals & Systems Ensemble Majority Vote Solutions",
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