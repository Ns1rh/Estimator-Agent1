# Estimator Agent Architecture

The goal of this project is to build an AI electrical estimator coworker.

The goal is not to produce miscellaneous reports, summarize PDFs, or collect disconnected automation experiments. Every primary feature should reduce the amount of work an electrical estimator performs while completing a bid.

## Primary workflow

```text
Project Folder
|
v
Understand the project
|
v
Understand the drawings
|
v
Perform electrical takeoff
|
v
Create LiveCount-ready takeoff
|
v
Produce Accubid-ready estimate data
|
v
Human review
```

## Main output contract

The primary workflow should converge toward these files only:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`

Each takeoff/export row should answer:

- item
- quantity
- sheet
- location
- confidence
- reason
- review required

## Do not rebuild native estimating software

Do not implement a custom takeoff engine, pricing engine, or estimating database if equivalent functionality already exists in LiveCount or Accubid.

Prefer native workflows first:

- LiveCount workflows
- Accubid workflows
- documented APIs
- import/export features
- UI automation
- customer-accessible automation interfaces

Only implement custom AI where it adds clear value beyond the native tools, such as:

- understanding drawings
- identifying relevant sheets/regions/schedules
- controlling LiveCount or Accubid
- validating takeoff results
- detecting omissions and inconsistencies
- producing estimator review summaries

The agent should augment the estimator and the existing software stack, not replace proven estimating systems with a weaker parallel system.

## Module categories

All modules should belong to one of these categories:

1. Project Intake
2. Drawing Intelligence
3. Symbol Detection
4. Schedule Understanding
5. Cross Checking
6. Estimator Output
7. LiveCount Integration
8. Accubid Integration
9. Experimental

Anything outside these categories should not be part of the primary estimator workflow.

## Current module map

| Current module/file | New category | Status | Notes |
|---|---|---:|---|
| `project_intake.py` | Project Intake | Keep | Should become the clean project-folder classifier for drawings, specs, addenda, schedules, and electrical sheets. |
| `drawing_estimator.py` | Drawing Intelligence / early Symbol Detection | Refactor | Currently text-heavy. Keep useful scanning pieces, but evolve toward visual drawing understanding and symbol detection. |
| `sheet_map.py` | Drawing Intelligence | Keep/refactor | Useful for connecting PDF pages to sheet names and titles. |
| `worker_mode.py` | Estimator Output / orchestration | Refactor | Should become the main coworker pipeline, not a report generator. |
| `web_accubid_prep.py` | Accubid Integration / Estimator Output | Refactor | Keep only if it produces clean Accubid-ready estimating data. |
| `livecount_tpx.py` | LiveCount Integration | Keep | Useful for reading LiveCount exports and validating real takeoff data. |
| `audit.py` | Cross Checking / Experimental | Refactor | Keep checking logic, but remove "audit report" as a primary product. |
| `drawing_check.py` | Cross Checking / Experimental | Refactor | Useful for validation, not primary estimator workflow yet. |
| `project_scan.py` | Experimental / training data prep | Move later | Useful for mining historical projects, but not part of day-to-day estimating workflow. |
| `training_set.py` | Experimental / training data prep | Move later | Support tool for improving detection, not primary workflow. |
| `validation.py` | Experimental / QA | Move later | Keep for detector scoring, but separate from estimator-facing workflow. |
| `estimating_agent_cli.py` | Interface / orchestration | Refactor | CLI should expose estimator actions, not old experiments as first-class commands. |
| `livecount_browser_control.mjs` | LiveCount Integration / Experimental | Keep isolated | Browser automation is useful, but only after reliable takeoff exists. |
| `accubid_uia_control.ps1` | Accubid Integration / Experimental | Keep isolated | Useful for UI exploration; do not make primary until data bridge is reliable. |
| One-off scripts: `gurnee_*`, `evaluate_*`, `score_*`, `inspect_*`, `build_gurnee_*` | Experimental | Move later | These are research artifacts and should not define the main product. |

## Development roadmap

### Phase 1: Project Intelligence

Input: project folder.

Automatically identify:

- drawings
- specifications
- addenda
- schedules
- electrical sheets
- lighting sheets
- power sheets
- fire alarm sheets
- low voltage sheets

Output: `project_dashboard.md`.

### Phase 2: Drawing Intelligence

Identify:

- legends
- schedules
- title blocks
- drawing regions
- electrical plan regions
- room names

Objective: know where important estimating information exists.

### Phase 3: Symbol Detection

Highest priority after Phase 1.

Implement one symbol category at a time:

1. light fixtures
2. exit signs
3. emergency lights
4. switches
5. receptacles
6. panels
7. disconnects
8. transformers
9. floor boxes
10. fire alarm devices

For every symbol:

- detect
- highlight
- count
- confidence score
- export

Do not move to the next symbol category until the current one is reliable.

### Phase 4: Schedule Understanding

Connect symbol tags to schedules.

Example:

```text
Fixture symbol A
|
v
Fixture Schedule
|
v
Actual fixture description
|
v
Accubid mapping placeholder
```

### Phase 5: Cross Checking

Compare:

- drawings
- schedules
- specifications
- addenda

Flag estimator-relevant issues:

- drawing count differs from schedule
- missing panel schedule
- missing specification
- possible duplicate symbols
- possible demolished work

### Phase 6: Estimator Output

Produce only the primary output contract:

- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`
- `project_dashboard.md`

### Phase 7: LiveCount Integration

Only after reliable internal takeoff exists.

Investigate LiveCount Auto Takeoff and import/export paths. If LiveCount Auto Takeoff is available, integrate with it instead of trying to replace it.

### Phase 8: Accubid Integration

Translate takeoff results into Accubid-ready assemblies and import templates.

Do not attempt pricing.

Do not attempt bid strategy.

Focus only on clean estimating data.

## Current implementation focus

The first-class user workflow is now:

```powershell
estimate-project --project-folder <PROJECT_FOLDER> --out-dir <OUTPUT_FOLDER>
```

This command should be the normal estimator entrypoint. It may call Phase 1, Phase 2, symbol detection, validation, LiveCount integration, and Accubid integration internally, but those lower-level tools should feel like backstage machinery.

The primary output contract remains:

- `project_dashboard.md`
- `takeoff_items.csv`
- `estimator_review.csv`
- `accubid_mapping.csv`
- `marked_up_drawings.pdf`

Any command that does not directly help this workflow should be treated as support/experimental, not as the product.
