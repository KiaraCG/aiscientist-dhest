import json

needed = [f"q{i}" for i in range(1, 61)]
path = "llm_output/reason-then-answer/Qwen3.8-27B/solutions_2021_autumn.json"
path = "llm_output/signals-and-systems/solutions_2017_autumn.json"
with open(path, "r") as f:
    data = json.load(f)
    questions = data.get("answers", data if isinstance(data, list) else [])

print(f"Total items in list: {len(questions)}")
ids = [q.get("id") for q in questions]
print(f"Unique IDs: {len(set(ids))}")

# Find any duplicates
from collections import Counter
duplicates = [qid for qid, count in Counter(ids).items() if count > 1]
print(f"Duplicate IDs found: {duplicates}")
missing = [i for i in needed if i not in ids]
print(f"Missing ids: {missing}")