# Estimator Agent Demo Guide

This project is a first-pass multi-scope electrical estimator review assistant.

It takes a project folder and produces a review package that helps an estimator inspect candidate quantities faster. The current workflow covers lighting and fire alarm device counts, creates marked drawings, prepares CSV review outputs, and creates an Accubid mapping template.

This is first-pass estimator review output, not final bid output.

## Current supported categories

- `light_fixture`
- `exit_sign`
- `emergency_light`
- `fire_alarm_device`

The current scope does not include receptacles, switches, panels, feeders, conduit, or pricing.

## What the project currently does

The main command:

1. scans a normal project folder,
2. identifies likely drawing and schedule PDFs,
3. selects likely lighting and fire alarm plan sheets,
4. renders those sheets,
5. detects supported symbol/tag categories,
6. creates marked drawings,
7. writes estimator review CSVs,
8. creates an Accubid mapping template for later estimator completion.

It does not replace LiveCount or Accubid. It prepares review data that can eventually support those workflows.

## Smoke demo command

Run this from the repository root:

```powershell
python work\create_demo_project.py --out-dir samples\safe_multi_scope_project --seed 1

python work\estimating_agent_cli.py estimate-project --project-folder samples\safe_multi_scope_project --out-dir outputs\estimator-package\safe-multi-scope-demo
```

Open this output folder:

```text
outputs\estimator-package\safe-multi-scope-demo
```

Expected top-level estimator package:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

## Demo health check

After running the smoke demo:

```powershell
python work\check_demo_outputs.py --out-dir outputs\estimator-package\safe-multi-scope-demo
```

This only checks that the expected demo files exist, the key CSVs have data rows, the marked PDF exists, and the dashboard clearly identifies itself as first-pass estimator review output.

## What each output file means

- `project_dashboard.md`  
  Plain-language estimator summary. Open this first.

- `takeoff_items.csv`  
  Candidate quantities grouped by project, source file, sheet, category, tag, confidence, evidence, and review status.

- `estimator_review.csv`  
  A simpler review table for checking detected quantities and schedule descriptions.

- `marked_up_drawings.pdf`  
  Visual markup showing where the agent found candidate symbols/tags.

- `accubid_mapping.csv`  
  A mapping template only. It helps an estimator map takeoff rows to Accubid items or assemblies later. It does not price work.

- `validation_answer_key_template.csv`  
  A review template. Fill in reviewed quantities from LiveCount, Accubid, or manual takeoff to score the agent.

## Recommended presentation order

1. `outputs\estimator-package\safe-multi-scope-demo\project_dashboard.md`
2. `outputs\estimator-package\safe-multi-scope-demo\takeoff_items.csv`
3. `outputs\estimator-package\safe-multi-scope-demo\marked_up_drawings.pdf`
4. `outputs\estimator-package\safe-multi-scope-demo\accubid_mapping.csv`
5. `outputs\capability-check\summary.md`
6. `outputs\capability-check-holdout\summary.md`

## Demo talking points

The tool takes a project folder and produces a first-pass multi-scope estimator review package. It currently supports light fixtures, exit signs, emergency lights, and fire alarm devices. It is not final bid output. It is meant to help an estimator review quantities faster and eventually prepare data for LiveCount/Accubid workflows.

Short version:

> Project folder in. First-pass estimator review package out. The estimator still reviews the quantities, but the tool organizes the drawings, marks candidates, writes CSV review files, and prepares an Accubid mapping template.

## Smoke demo vs randomized checks

The smoke demo proves the end-to-end workflow works on one safe synthetic project.

The randomized capability check runs several different safe synthetic projects so the demo is not tuned to one fixed drawing.

The holdout check runs different seeds after the normal check. It is a quick guard against overfitting the current demo cases.

## Randomized capability checks

Run:

```powershell
python work\run_capability_check.py --cases 5 --out-dir outputs\capability-check

python work\run_capability_check.py --cases 5 --seed-start 6 --out-dir outputs\capability-check-holdout
```

Current normal randomized check, seeds 1-5:

- Cases completed: 5/5
- Expected quantity: 99
- AI quantity: 96
- Difference: -3
- Percent difference: -3.03%
- Extra AI rows: 0

Current holdout check, seeds 6-10:

- Cases completed: 5/5
- Expected quantity: 92
- AI quantity: 91
- Difference: -1
- Percent difference: -1.09%
- Extra AI rows: 0

These are honest development metrics on safe synthetic projects. They do not prove production accuracy on real drawings.

## Known limitations

- Real drawings may be harder than synthetic drawings.
- Scanned PDFs may require OCR later.
- Unusual title blocks, dense legends, sidebars, or crowded notes may still cause misses.
- Current detection is conservative and may slightly undercount occasional EXIT, SD, or light fixture tags.
- Quantities require estimator review before bid use.
- Current scope does not include receptacles, switches, panels, feeders, conduit, or pricing.

## Next development steps

1. Improve symbol detection on real, approved, reviewed drawing sets.
2. Add OCR support for scanned PDFs.
3. Improve schedule and legend matching for lighting and fire alarm devices.
4. Add the next estimator-value category only after current categories are reliable.
5. Continue preparing clean outputs that can support LiveCount and Accubid workflows without replacing those tools.
