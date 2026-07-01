# Private Company Pilot Workflow

This workflow is for local private validation against completed company projects and reviewed estimator quantities.

Company files should stay outside this Git repo. Do not commit drawings, specifications, LiveCount exports, Accubid exports, reviewed takeoffs, screenshots, real marked-up drawings, pricing files, or bid strategy notes.

The safe synthetic demo is for presentation. The company pilot is for real private validation and future learning.

## Recommended private folder structure

Use a local folder outside the repo, for example:

```text
C:\EstimatorAgentData\company_projects\PROJECT_ID\
  input\
    drawings\
    specs\
    addenda\
  reviewed\
    reviewed_takeoff.csv
    livecount_export.csv
    accubid_mapping_export.csv
    estimator_notes.md
  answer_key\
    validation_answer_key.csv
```

The estimator runs only on:

```text
C:\EstimatorAgentData\company_projects\PROJECT_ID\input
```

Reviewed files and answer keys are used only after `estimate-project` finishes.

If the input folder also contains previous proposal/estimate summaries or LiveCount `.tpx` exports, the agent may extract high-level reference quantities for comparison. Those quantities are reported separately under `_internal\reference_scope\` and `_internal\livecount_reference\`. They are not treated as AI drawing detections.

## Choose a completed project

Choose a project where:

- the drawings/specs used for the estimate are available,
- the estimator-reviewed quantities are available,
- the project has lighting or fire alarm scope that overlaps the current supported categories,
- the reviewed quantities can be exported or copied into a simple answer-key CSV.

Start with one clean completed project before running a batch.

## Create the private input folder

Copy only the files needed for the pilot into:

```text
C:\EstimatorAgentData\company_projects\PROJECT_ID\input
```

Suggested subfolders:

```text
input\drawings
input\specs
input\addenda
```

Do not put these files in `samples\`, `outputs\`, or any folder inside the Git repo.

## Create the reviewed answer key

Create:

```text
C:\EstimatorAgentData\company_projects\PROJECT_ID\answer_key\validation_answer_key.csv
```

Preferred format:

```csv
project_name,source_file,sheet_number,sheet_name,category,tag,reviewed_quantity,notes
PROJECT_ID,,E2.1,LIGHTING PLAN,light_fixture,A1,12,Reviewed estimator quantity
PROJECT_ID,,E2.1,LIGHTING PLAN,exit_sign,EXIT,4,Reviewed estimator quantity
PROJECT_ID,,FA1.1,FIRE ALARM PLAN,fire_alarm_device,SD,18,Reviewed estimator quantity
```

Simpler category/tag format is also supported:

```csv
category,tag,reviewed_quantity,notes
light_fixture,A1,12,Reviewed total
exit_sign,EXIT,4,Reviewed total
fire_alarm_device,SD,18,Reviewed total
```

Category-only totals are also accepted when sheet/tag detail is not available:

```csv
category,reviewed_quantity,notes
light_fixture,120,Reviewed total across project
fire_alarm_device,84,Reviewed total across project
```

Category-only comparisons are high-level checks. They are useful for early signal, but sheet/tag-level answer keys are more diagnostic.

## Run a single company pilot

```powershell
python work\run_company_pilot.py --project-dir "C:\EstimatorAgentData\company_projects\PROJECT_ID" --out-dir "C:\EstimatorAgentData\outputs\PROJECT_ID"
```

The script will:

1. find `input\`,
2. run `estimate-project` on `input\` only,
3. check for `answer_key\validation_answer_key.csv`,
4. run validation if the answer key exists,
5. write `pilot_summary.md` in the private output folder.

Equivalent manual commands:

```powershell
python work\estimating_agent_cli.py estimate-project --project-folder "C:\EstimatorAgentData\company_projects\PROJECT_ID\input" --out-dir "C:\EstimatorAgentData\outputs\PROJECT_ID"

python work\estimating_agent_cli.py validate-detections-csv --detections "C:\EstimatorAgentData\outputs\PROJECT_ID\takeoff_items.csv" --answer-key "C:\EstimatorAgentData\company_projects\PROJECT_ID\answer_key\validation_answer_key.csv" --out-dir "C:\EstimatorAgentData\outputs\PROJECT_ID\validation"
```

The estimator package keeps the normal six output files:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

For real company packages, open `project_dashboard.md` first. It separates:

- AI detections from drawings
- reference quantities from previous estimates
- reference quantities from LiveCount/TPX exports
- items needing estimator review

Rendered fallback pages may still appear in `marked_up_drawings.pdf`, but review-only pages are labeled and excluded from automatic visual counts.

## Run a multi-project company evaluation

```powershell
python work\run_company_pilot_batch.py --projects-root "C:\EstimatorAgentData\company_projects" --out-dir "C:\EstimatorAgentData\outputs\company-pilot-batch"
```

The batch runner will:

- run each project folder that has an `input\` folder,
- run validation when `answer_key\validation_answer_key.csv` exists,
- write `summary.md` and `summary.csv`,
- summarize matches, mismatches, missing AI rows, extra AI rows, and category/status counts.

## Interpret mismatches

Validation row statuses:

- `MATCH`: AI quantity equals reviewed quantity for that comparison row.
- `MISMATCH`: both AI and reviewed quantities exist but differ.
- `AI_MISSING`: reviewed quantity exists, but AI did not detect it.
- `ESTIMATOR_MISSING`: AI detected something not present in the reviewed answer key.

Review `marked_up_drawings.pdf`, `takeoff_items.csv`, and `validation\symbol_detection_validation.csv` together. A mismatch can mean:

- the detector missed a symbol,
- the answer key is grouped differently,
- a tag was read from a legend or schedule,
- the reviewed quantity is broader than the current supported categories,
- the drawing is scanned or not searchable.

## What data should never be committed

Never commit:

- company drawings or specs,
- addenda,
- LiveCount files or exports,
- Accubid files or exports,
- reviewed takeoff files,
- pricing files,
- real marked-up drawings,
- screenshots of real project drawings,
- confidential estimator notes or bid strategy.

Keep those under a private local folder such as:

```text
C:\EstimatorAgentData
```

## Mapping memory direction

The next private-learning step is a local mapping-memory file that captures reviewed mapping patterns without prices.

Example non-pricing fields:

- category
- tag
- schedule_description
- reviewed_quantity
- accubid_item_name_or_placeholder
- accubid_assembly_name_or_placeholder
- estimator_notes
- source_project_id

Do not include unit price, labor rate, markup, bid total, or confidential strategy notes unless intentionally provided for a private local-only experiment.

This is documented as the next step, not implemented as a learning database yet.
