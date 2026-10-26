# Exam workspaces

Private exam profiles for the toolkit. Each subdirectory is one marking version
(`exam_config.json` + `rubric_manifest.json` + `Rubrics/` + `Prompts/` + `RawExams/`).

Workspaces prefixed with course names were generated from the JSON baseline exams
via `tools/json_exam_to_workspace.py`. Original JSON lives in each workspace's
`source/` folder. Regenerate after baseline updates:

```bash
python tools/json_exam_to_workspace.py --all --overwrite
python prepare_exam.py --config workspaces/<workspace>/exam_config.json --check
```

Keep `approved_for_scoring=false` until an instructor approves the rubric PDF and
manifest. Copy `.env.example` here for live scoring (not committed).
