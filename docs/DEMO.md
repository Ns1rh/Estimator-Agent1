# Estimator Agent Demo

This project currently demonstrates a first-pass electrical takeoff review workflow for light fixtures, exit signs, emergency lights, and fire alarm devices.

It does not use company drawings. It does not price work. It does not create an Accubid database. It is not final bid output.

## 1. Smoke demo

Purpose: prove the main workflow works end to end.

```powershell
python work\create_demo_project.py --out-dir "samples\safe_light_fixture_project_v2" --seed 1

python work\estimating_agent_cli.py estimate-project --project-folder "samples\safe_light_fixture_project_v2" --out-dir "outputs\estimator-package\safe-demo-final"
```

Expected top-level estimator package:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

## 2. Randomized capability check

Purpose: check whether the workflow works beyond one fixed drawing.

```powershell
python work\run_capability_check.py --cases 5 --out-dir "outputs\capability-check"
```

This generates multiple safe synthetic projects using different seeds, runs `estimate-project` blind, validates after the fact using generated answer keys, and writes:

- `outputs\capability-check\summary.md`
- `outputs\capability-check\summary.csv`

These metrics are honest development metrics. They do not prove production accuracy on real drawings.

## 3. Future real/public project testing

Later, run the same `estimate-project` command against reviewed public project documents or approved internal projects.

Real outputs still require estimator review, especially:

- detected quantities
- schedule descriptions
- tags missing from schedule
- schedule tags not found on selected plan sheets
- Accubid item/assembly mapping

## How to show the current demo

Open these in order:

1. `project_dashboard.md`
2. `takeoff_items.csv`
3. `marked_up_drawings.pdf`
4. `accubid_mapping.csv`
5. `outputs\capability-check\summary.md` if available

The short explanation:

> Project folder in. First-pass estimator review package out. The smoke demo proves the workflow, and the randomized capability check gives a more honest measure of current detection ability.
