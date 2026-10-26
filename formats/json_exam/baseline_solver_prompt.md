# Baseline LLM solver prompt (reference only)

The basic baseline called the model with structured **exam JSON** in the user message
and expected `{ "examId", "answers": [{ "id", "answer" }] }` back. That flow is
**not** what `score_exams.py` uses. It is kept here so you can compare wording when
adapting `Prompts/prompt.template.txt` or `exam_config.json` notes.

Typical baseline pattern (from `exam_taker.py`):

- Role: expert solver for the course (e.g. Signals and Systems).
- Input: full `exam_*.json` embedded in the prompt.
- Output: strict JSON with one `answer` per question `id` (option text for MC).
- Endpoint: SwissAI research API (`SWISSAI_RESEARCH_API_KEY`), not the toolkit Azure/OpenAI scorer.

The toolkit instead uploads **rubric PDF + student PDF** and expects per-criterion
`grades` with explanations. Use the generated workspaces under `workspaces/` and
the standard scoring template copied into each `Prompts/prompt.template.txt`.
