# Final Demo Verification Checklist

Verification date: 2026-06-30

Current checkpoint verified: `8529129 Make marked drawing rendering robust`

This project is first-pass estimator review output, not final bid output. It does not price work, does not create an Accubid database, and does not replace LiveCount or Accubid.

## What this demo shows

The estimator assistant takes a project folder or single PDF, selects likely electrical plan sheets, renders drawings, detects supported first-pass categories, creates marked drawings, writes estimator review CSVs, prepares an Accubid mapping template, and validates results against answer keys when provided after the run.

## Supported first-pass categories

- `light_fixture`
- `exit_sign`
- `emergency_light`
- `fire_alarm_device`

## Commands run and status

All commands below were run from the repo root.

| Step | Command | Status |
|---|---|---|
| Create safe demo project | `python work\create_demo_project.py --out-dir samples\safe_multi_scope_project --seed 1` | Passed |
| Run safe demo package | `python work\estimating_agent_cli.py estimate-project --project-folder samples\safe_multi_scope_project --out-dir outputs\estimator-package\safe-multi-scope-demo` | Passed |
| Check safe demo outputs | `python work\check_demo_outputs.py --out-dir outputs\estimator-package\safe-multi-scope-demo` | Passed |
| Run randomized capability check | `python work\run_capability_check.py --cases 5 --out-dir outputs\capability-check` | Passed |
| Run holdout capability check | `python work\run_capability_check.py --cases 5 --seed-start 6 --out-dir outputs\capability-check-holdout` | Passed |
| Run unseen safe input | `python work\estimating_agent_cli.py estimate-project --project-folder .\estimator_unseen_test_input\input --out-dir outputs\estimator-package\unseen-safe-test` | Passed |
| Validate unseen safe input | `python work\estimating_agent_cli.py validate-detections-csv --detections outputs\estimator-package\unseen-safe-test\takeoff_items.csv --answer-key .\estimator_unseen_test_input\answer_key\validation_answer_key.csv --out-dir outputs\estimator-package\unseen-safe-test\validation` | Passed |

Note: for the unseen safe validation, the generated safe answer key was copied into `estimator_unseen_test_input\answer_key\validation_answer_key.csv` so the validation command could run using the requested path. The answer key was used only after `estimate-project` finished.

## Output folders

- Safe demo package: `outputs\estimator-package\safe-multi-scope-demo`
- Randomized capability check: `outputs\capability-check`
- Holdout capability check: `outputs\capability-check-holdout`
- Unseen safe test package: `outputs\estimator-package\unseen-safe-test`
- Unseen safe validation: `outputs\estimator-package\unseen-safe-test\validation`

## Required estimator package files

Both the safe demo package and unseen safe package created the required six estimator-facing files:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

Safe demo file sizes:

| File | Status |
|---|---|
| `project_dashboard.md` | Created |
| `takeoff_items.csv` | Created with data rows |
| `estimator_review.csv` | Created with data rows |
| `accubid_mapping.csv` | Created with data rows |
| `marked_up_drawings.pdf` | Created, non-empty, not placeholder |
| `validation_answer_key_template.csv` | Created |

## Marked drawing status

Safe demo:

- `marked_up_drawings.pdf` was created.
- Health check confirmed it is not the placeholder.
- Rendered page images created: 2.

Unseen safe input:

- `marked_up_drawings.pdf` was created.
- Health check confirmed it is not the placeholder.
- Rendered page images created: 2.

Open this during the demo:

```text
outputs\estimator-package\safe-multi-scope-demo\marked_up_drawings.pdf
```

## Render fallback status

Rendering diagnostics are available here:

- `outputs\estimator-package\safe-multi-scope-demo\_internal\render_debug.md`
- `outputs\estimator-package\unseen-safe-test\_internal\render_debug.md`

Observed render status:

- `pdftoppm` found: `C:\Users\namid\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe`
- PyMuPDF available: yes
- Safe demo render method used: `pdftoppm`
- Unseen safe render method used: `pdftoppm`
- PyMuPDF fallback is installed and available if Poppler rendering fails.

## Safe demo detected items

Safe demo package detected:

| Category | Tag | Quantity | Sheet |
|---|---:|---:|---|
| `emergency_light` | `EM1` | 2 | `E2.1` |
| `exit_sign` | `EXIT` | 4 | `E2.1` |
| `light_fixture` | `B1` | 5 | `E2.1` |
| `fire_alarm_device` | `CM` | 3 | `FA1.1` |
| `fire_alarm_device` | `PULL` | 4 | `FA1.1` |
| `fire_alarm_device` | `SD` | 5 | `FA1.1` |

## Randomized capability metrics

Output:

```text
outputs\capability-check\summary.md
```

Seeds 1-5:

- Cases run: 5
- Cases completed without crashing: 5
- Total expected quantity: 99
- Total AI quantity: 96
- Quantity difference: -3
- Percent difference: -3.03%
- Exact match rows: 29
- Mismatched rows: 2
- Missing AI rows: 1
- Extra AI rows: 0

Category breakdown:

- `emergency_light`: expected 6; AI 6; diff +0
- `exit_sign`: expected 16; AI 15; diff -1
- `fire_alarm_device`: expected 45; AI 44; diff -1
- `light_fixture`: expected 32; AI 31; diff -1

## Holdout capability metrics

Output:

```text
outputs\capability-check-holdout\summary.md
```

Seeds 6-10:

- Cases run: 5
- Cases completed without crashing: 5
- Total expected quantity: 92
- Total AI quantity: 91
- Quantity difference: -1
- Percent difference: -1.09%
- Exact match rows: 29
- Mismatched rows: 1
- Missing AI rows: 0
- Extra AI rows: 0

Category breakdown:

- `emergency_light`: expected 3; AI 3; diff +0
- `exit_sign`: expected 12; AI 12; diff +0
- `fire_alarm_device`: expected 47; AI 46; diff -1
- `light_fixture`: expected 30; AI 30; diff +0

## Unseen safe input validation result

Output:

```text
outputs\estimator-package\unseen-safe-test\validation\SYMBOL_DETECTION_VALIDATION.md
```

Result:

- AI detected quantity: 21
- Answer-key quantity: 21
- Category/sheet/tag rows compared: 7
- Exact category/sheet/tag quantity matches: 7
- Category/sheet/tag rows needing review: 0
- Conservative tag-count score: 100.00%

Matched rows:

| Sheet | Category | Tag | AI Qty | Answer Qty | Status |
|---|---|---:|---:|---:|---|
| `EL1.1` | `exit_sign` | `EXIT` | 5 | 5 | MATCH |
| `FA1.1` | `fire_alarm_device` | `FACP` | 4 | 4 | MATCH |
| `FA1.1` | `fire_alarm_device` | `HD` | 4 | 4 | MATCH |
| `FA1.1` | `fire_alarm_device` | `HS` | 2 | 2 | MATCH |
| `FA1.1` | `fire_alarm_device` | `PULL` | 2 | 2 | MATCH |
| `EL1.1` | `light_fixture` | `A1` | 3 | 3 | MATCH |
| `EL1.1` | `light_fixture` | `A3` | 1 | 1 | MATCH |

## Exact files to open during the demo

Open in this order:

1. `outputs\estimator-package\safe-multi-scope-demo\project_dashboard.md`
2. `outputs\estimator-package\safe-multi-scope-demo\takeoff_items.csv`
3. `outputs\estimator-package\safe-multi-scope-demo\marked_up_drawings.pdf`
4. `outputs\estimator-package\safe-multi-scope-demo\accubid_mapping.csv`
5. `outputs\capability-check\summary.md`
6. `outputs\capability-check-holdout\summary.md`
7. `outputs\estimator-package\unseen-safe-test\validation\SYMBOL_DETECTION_VALIDATION.md`
8. `outputs\estimator-package\safe-multi-scope-demo\_internal\render_debug.md` if asked about rendering reliability

## Suggested talking points

Short version:

> This is a first-pass multi-scope electrical estimator review assistant. It takes a project folder, finds likely lighting and fire alarm plan sheets, renders the drawings, detects supported count categories, produces marked drawings, writes estimator review CSVs, and prepares an Accubid mapping template. It is not final bid output and it does not price work.

Capability explanation:

> The safe demo proves the workflow end-to-end. The randomized check tests five generated projects so we know it is not only working on one fixed drawing. The holdout check uses different seeds as a basic overfitting check.

Marked drawing explanation:

> The marked drawings are now real rendered drawing pages with detected items highlighted. The health check fails if the marked PDF is only the old placeholder.

Validation explanation:

> The answer key is only used after the estimator package is generated. That keeps the detection honest. On the unseen safe input, the validation matched 21 out of 21 reviewed quantities.

Private company direction:

> The safe synthetic projects are for presentation. Real improvement should come from private company pilots using completed reviewed projects stored outside the repo. Company files should not be committed.

## Known limitations to mention

- This is first-pass estimator review output, not final bid output.
- Quantities require estimator review before bid use.
- The current categories are limited to lighting and fire alarm related counts listed above.
- It does not include receptacles, switches, panels, feeders, conduit, pricing, labor, bid strategy, or an Accubid database.
- Real scanned PDFs may need OCR.
- Real drawings can have unusual legends, title blocks, dense notes, or symbols that require more detector tuning.
- The current detector is conservative and can slightly undercount in randomized tests.

## Demo readiness conclusion

The demo is ready to show as:

> A first-pass multi-scope electrical estimator review assistant, currently covering lighting and fire alarm device counts, with real marked drawings, CSV review outputs, Accubid mapping templates, render diagnostics, randomized capability checks, holdout checks, and unseen safe-input validation.
