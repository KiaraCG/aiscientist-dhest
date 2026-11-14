import json

with open("solutions_2021_autumn.json", "r") as f:
    data = json.load(f)
    questions = data.get("answers", data if isinstance(data, list) else [])

print(f"Total items in list: {len(questions)}")
ids = [q.get("id") for q in questions]
print(f"Unique IDs: {len(set(ids))}")

# Find any duplicates
from collections import Counter
duplicates = [qid for qid, count in Counter(ids).items() if count > 1]
print(f"Duplicate IDs found: {duplicates}")
print(sorted(ids))