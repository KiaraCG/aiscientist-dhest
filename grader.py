import json
from jsonschema import validate, ValidationError


def grade_llm_exam(solution_path, llm_output_path, output_schema_path):
    # 1. Load schemas and files
    with open(solution_path, 'r') as f:
        solution_key = json.load(f)

    with open(llm_output_path, 'r') as f:
        submission = json.load(f)

    with open(output_schema_path, 'r') as f:
        llm_schema = json.load(f)

    # 2. Validate LLM output structure via JSON Schema
    try:
        validate(instance=submission, schema=llm_schema)
        print("Schema Validation Passed: LLM output format is correct.\n")
    except ValidationError as e:
        print(f"Schema Validation Failed: {e.message}")
        return

    # 3. Grade the submission
    total_score = 0
    max_score = 0
    detailed_results = []

    student_answers = {item["id"]: item["answer"] for item in submission.get("answers", [])}

    for q_id, key in solution_key.items():
        max_score += key["points"]
        student_ans = student_answers.get(q_id)
        q_type = key["type"]
        earned = 0
        status = "Incorrect"

        if student_ans is None:
            detailed_results.append({"id": q_id, "status": "Unanswered", "earned": 0})
            continue

        if q_type == "single-choice":
            if student_ans == key.get("correctAnswer"):
                earned = key["points"]
                status = "Correct"

        elif q_type == "multiple-choice":
            if isinstance(student_ans, list) and set(student_ans) == set(key.get("correctAnswers", [])):
                earned = key["points"]
                status = "Correct"

        elif q_type == "number":
            tolerance = key.get("tolerance", 0)
            try:
                if abs(float(student_ans) - key.get("correctAnswer", 0)) <= tolerance:
                    earned = key["points"]
                    status = "Correct"
            except (ValueError, TypeError):
                status = "Invalid Number Format"

        elif q_type == "free-text":
            status = "Pending Review"
            earned = 0  # Placeholder for manual or LLM-as-a-judge scoring

        total_score += earned
        detailed_results.append({
            "id": q_id,
            "status": status,
            "earnedPoints": earned,
            "maxPoints": key["points"]
        })

    # 4. Print Summary
    print(f"--- Exam Grading Report: {submission.get('examId')} ---")
    print(f"Total Score: {total_score} / {max_score}\n")
    print("Breakdown:")
    print(json.dumps(detailed_results, indent=2))


if __name__ == "__main__":
    EXAM_DIR = "signals-and-systems"
    EXAM_ID = "hs21"

    grade_llm_exam(
        solution_path=f"data/{EXAM_DIR}/solution_{EXAM_ID}.json",
        llm_output_path=f"llm_output/{EXAM_DIR}/output_{EXAM_ID}.json",
        output_schema_path=f"json_schemas/llm_output_schema.json"
    )