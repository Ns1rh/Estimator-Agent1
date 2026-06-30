# Estimator Agent Demo

This demo uses a synthetic light-fixture project. It does not contain company drawings.

## 1. Create the safe demo project

```powershell
python work\create_demo_project.py --out-dir "samples\safe_light_fixture_project"
```

## 2. Run the estimator package workflow

```powershell
python work\estimating_agent_cli.py estimate-project --project-folder "samples\safe_light_fixture_project" --out-dir "outputs\estimator-package\safe-demo"
```

## 3. Open the outputs

The top-level estimator package should contain:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

## What to show

Start with `project_dashboard.md`, then open `takeoff_items.csv` and `marked_up_drawings.pdf`.

The important story is:

> Project folder goes in. A first-pass light fixture takeoff review package comes out.

The output is still estimator-reviewed. It is not final bid output.
