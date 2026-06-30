# Estimator Agent

AI electrical estimator coworker project.

The goal is not to replace LiveCount or Accubid. The agent should use native LiveCount/Accubid workflows, imports, exports, APIs, or UI automation wherever possible, and only add custom AI where it helps an estimator:

- understand project folders
- identify electrical sheets
- understand drawing pages/regions
- detect/count symbols for review
- validate takeoff results
- prepare LiveCount/Accubid-ready data

## Current workflow

```text
Project folder
-> Project Intelligence
-> Drawing Intelligence
-> Symbol Detection
-> Schedule Understanding
-> Estimator review package
-> LiveCount/Accubid-ready mapping
```

## Main command

Run from the repo root with Python available:

```powershell
python work\estimating_agent_cli.py estimate-project --project-folder "PATH_TO_PROJECT" --out-dir "outputs\estimator-package\PROJECT"
```

This creates one estimator review package:

- `project_dashboard.md` - plain-English run summary and next review steps
- `takeoff_items.csv` - detected/countable items with confidence and schedule context
- `estimator_review.csv` - item-level evidence for review
- `accubid_mapping.csv` - Accubid mapping template; no pricing
- `marked_up_drawings.pdf` - drawing markups when sheets can be rendered
- `validation_answer_key_template.csv` - fill reviewed quantities here to score the agent

## Current capability

The current useful workflow is light-fixture focused:

- finds likely lighting/electrical plan sheets
- renders selected sheets
- detects searchable light fixture tags on lighting plans
- groups counts by sheet and fixture tag
- connects many fixture tags to fixture schedule descriptions when searchable schedule text exists
- produces an Accubid-ready mapping template for estimator review

All quantities are marked for estimator review. This is not final bid output yet.

## Validation command

After an estimator fills `validation_answer_key_template.csv` with reviewed quantities:

```powershell
python work\estimating_agent_cli.py validate-detections-csv --detections "outputs\estimator-package\PROJECT\takeoff_items.csv" --answer-key "outputs\estimator-package\PROJECT\validation_answer_key_template.csv" --out-dir "outputs\estimator-package\PROJECT\validation"
```

## Important safety rule

Do not commit company project data.

Keep these out of Git:

- drawings/spec PDFs
- TPX/LiveCount exports
- Accubid estimate/database files
- marked drawings from real projects
- screenshots of company drawings
- network-share paths containing project data

The `.gitignore` blocks these by default.
