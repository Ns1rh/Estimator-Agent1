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
-> Estimator review
-> LiveCount/Accubid integration
```

## Main commands

Run from the repo root with Python available:

```powershell
python work\estimating_agent_cli.py intake-project --project-folder "PATH_TO_PROJECT" --out-dir "outputs\intake-packets\PROJECT"
python work\estimating_agent_cli.py drawing-intelligence --project-folder "PATH_TO_PROJECT" --sheet-index "outputs\intake-packets\PROJECT\electrical_sheet_index.csv" --out-dir "outputs\coworker-estimates\PROJECT-drawing-intelligence"
python work\estimating_agent_cli.py detect-light-fixtures --rendered-sheets-dir "outputs\coworker-estimates\PROJECT-drawing-intelligence\rendered_sheets" --out-dir "outputs\coworker-estimates\PROJECT-light-fixtures"
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

