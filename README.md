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
- detects searchable light fixture, exit sign, emergency light, and fire alarm device tags on likely plan sheets
- groups counts by category, sheet, and tag
- connects many tags to schedule descriptions when searchable schedule text exists
- produces an Accubid-ready mapping template for estimator review

All quantities are marked for estimator review. This is not final bid output yet.

## Validation command

After an estimator fills `validation_answer_key_template.csv` with reviewed quantities:

```powershell
python work\estimating_agent_cli.py validate-detections-csv --detections "outputs\estimator-package\PROJECT\takeoff_items.csv" --answer-key "outputs\estimator-package\PROJECT\validation_answer_key_template.csv" --out-dir "outputs\estimator-package\PROJECT\validation"
```

## Safe demo and capability check

Create a safe synthetic project and run the main workflow:

```powershell
python work\create_demo_project.py --out-dir "samples\safe_light_fixture_project_v2" --seed 1
python work\estimating_agent_cli.py estimate-project --project-folder "samples\safe_light_fixture_project_v2" --out-dir "outputs\estimator-package\safe-demo-final"
```

Run a randomized development-only capability check:

```powershell
python work\run_capability_check.py --cases 5 --out-dir "outputs\capability-check"
```

The randomized check helps show whether the tool works beyond one fixed drawing. It still uses safe synthetic projects and does not prove production accuracy on real drawings.

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
