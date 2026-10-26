# JSON exam formats (baseline pipeline)

These JSON Schema files describe the structured exam format used in the companion
baseline project (`exam_*.json`, `solution_*.json`, LLM `answers` output).
The professor's toolkit scores **whole PDF submissions** with a different result
contract (`grades` per rubric criterion). The schemas here document that baseline
format; adapted toolkit workspaces live under `workspaces/`.

| File | Role |
|---|---|
| `exam_schema.json` | Question list sent to the model (MC, numeric, free-text). |
| `solution_schema.json` | Instructor key: correct options, tolerances, sample answers. |
| `llm_output_schema.json` | Baseline model output: `{ examId, answers[] }`. |

To generate toolkit manifests and rubric PDFs from baseline JSON, use:

```bash
python -m pip install -r requirements-dev.txt   # reportlab, for rubric PDFs
python tools/json_exam_to_workspace.py --all
python prepare_exam.py --config workspaces/<name>/exam_config.json --check
```

Source copies of each exam JSON pair are kept in each workspace's `source/` folder.
