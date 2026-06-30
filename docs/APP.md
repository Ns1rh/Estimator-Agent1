# New Age Electric Estimator Assistant desktop app

This project now includes a simple local Windows desktop interface for the estimator workflow.

Launch it from the project folder:

```powershell
python work\estimator_agent_app.py
```

The app is a local wrapper around the existing CLI. It does not replace the estimator engine, LiveCount, Accubid, or any native estimating database.

## What the app does

The app lets an estimator:

1. Select a project folder or a single PDF drawing file.
2. Select an output folder.
3. Run `estimate-project`.
4. Watch live progress and command logs.
5. Open the generated estimator package files.
6. Run validation against a reviewed answer-key CSV.
7. Run the safe demo and check the current output package.

Visible reminder in the app:

> This is first-pass estimator review output, not final bid output.

## Required estimator package files

The app keeps the existing output contract unchanged:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `validation_answer_key_template.csv`

## Branding and logo

The app title is:

`New Age Electric Estimator Assistant`

The header displays:

- `New Age Electric LLC`
- `First-pass electrical takeoff review assistant`
- `Burbank, CA`

Optional logo support is included. Place a real approved company logo PNG at either:

- `assets\branding\new_age_electric_logo.png`
- `work\assets\branding\new_age_electric_logo.png`

If no logo file exists, the app shows a text placeholder:

`NEW AGE ELECTRIC LLC`

The app does not generate, scrape, download, or invent a logo.

## Running a real local/private test

1. Open the app.
2. Click `Browse Folder` or `Browse PDF`.
3. Choose an output folder. A local private folder is recommended for company files, for example:

```powershell
C:\EstimatorAgentData\local_tests\PROJECT_NAME\output
```

4. Click `Run Estimate`.
5. Review:
   - `project_dashboard.md`
   - `takeoff_items.csv`
   - `estimator_review.csv`
   - `marked_up_drawings.pdf`

Company drawings, specs, marked drawings, LiveCount files, Accubid files, pricing files, and private outputs should stay local/private and should not be committed to Git.

## Running the safe demo from the app

Click `Run Safe Demo`.

The app runs:

```powershell
python work\create_demo_project.py --out-dir samples\safe_multi_scope_project --seed 1
python work\estimating_agent_cli.py estimate-project --project-folder samples\safe_multi_scope_project --out-dir outputs\estimator-package\safe-multi-scope-demo
```

Then it sets the output folder to:

```powershell
outputs\estimator-package\safe-multi-scope-demo
```

Use `Check Current Output Package` to run the existing health check:

```powershell
python work\check_demo_outputs.py --out-dir "<selected_output>"
```

## Validation

Validation requires reviewed quantities from an estimator, LiveCount export, Accubid export, or manually prepared CSV.

1. Run an estimate first.
2. Select an answer key CSV.
3. Click `Run Validation`.

The app runs:

```powershell
python work\estimating_agent_cli.py validate-detections-csv --detections "<out_dir>\takeoff_items.csv" --answer-key "<answer_key_csv>" --out-dir "<out_dir>\validation"
```

Then open:

```powershell
<out_dir>\validation\SYMBOL_DETECTION_VALIDATION.md
```

## Current supported first-pass categories

- `light_fixture`
- `exit_sign`
- `emergency_light`
- `fire_alarm_device`

## Current limitations

- This is estimator review output, not a final bid.
- The app does not perform pricing.
- The app does not create an Accubid database.
- The app does not replace LiveCount or Accubid.
- Quantities require estimator review.
- PDF rendering depends on available local renderers such as Poppler/`pdftoppm` or PyMuPDF fallback.

## Suggested next UI improvement

Add a small results summary panel after each estimate showing:

- total takeoff rows
- detected categories
- marked drawing page count
- whether any placeholder or render warnings were found
