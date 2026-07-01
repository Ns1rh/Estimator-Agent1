# Symbol Library

The estimator uses symbols in this order:

1. Project legend/templates found in the current drawing package.
2. Private company symbols when `ESTIMATOR_SYMBOL_LIBRARY_DIR` is set.
3. Starter symbol taxonomy in the repo.
4. Existing embedded-label matching.
5. Geometry fallback, such as RCP repeated rectangles.

This keeps the agent estimator-like: the current project's legend wins, company reviewed symbols help when the project has no usable legend, and generic starter metadata is only a fallback.

## Starter Library

Starter metadata lives here:

```text
work\estimating_agent\symbol_library\starter\symbols.csv
```

The starter CSV is taxonomy and matching guidance only. It does not contain copied website symbol images.

Source notes live here:

```text
work\estimating_agent\symbol_library\starter\sources\source_manifest.csv
```

Use `source_manifest.csv` as a checklist of possible references and licensing status. Do not copy website images into the repo unless reuse rights are explicitly verified.

## Project Legend Templates

When a project includes symbol legends, fixture schedules, device schedules, or similar pages, the estimator records project-specific template rows under:

```text
_internal\symbol_templates\symbol_templates.csv
```

Project templates are preferred over all generic library entries.

## Private Company Symbol Library

Company/private symbol crops should stay outside Git, for example:

```text
C:\EstimatorAgentData\symbol_library\company_symbols
```

To enable private symbols during an estimator run, set:

```powershell
$env:ESTIMATOR_SYMBOL_LIBRARY_DIR = "C:\EstimatorAgentData\symbol_library\company_symbols"
```

The expected promoted library file is:

```text
C:\EstimatorAgentData\symbol_library\company_symbols\symbols.csv
```

Do not commit company drawings, harvested crops, real marked drawings, pricing files, Accubid files, LiveCount files, or private outputs.

## Ingest Approved Local Symbol Sheets

Use only approved local PDFs/images/SVGs where reuse is allowed or internal use is permitted:

```powershell
python work\ingest_symbol_source.py --source-file "<local approved PDF/PNG/SVG>" --source-name "<name>" --license-status "<status>" --out-dir "C:\EstimatorAgentData\symbol_library\company_symbols"
```

The ingestion script writes:

```text
symbol_candidates.csv
crops\
rendered\
```

Candidates are review-only until a human marks `approved=yes` or `review_status=approved`.

## Promote Approved Candidates

After reviewing `symbol_candidates.csv`, promote only approved rows:

```powershell
python work\promote_symbol_candidates.py --candidates "C:\EstimatorAgentData\symbol_library\company_symbols\symbol_candidates.csv" --out-library "C:\EstimatorAgentData\symbol_library\company_symbols"
```

The promotion script appends approved entries into:

```text
C:\EstimatorAgentData\symbol_library\company_symbols\symbols.csv
```

## Correction Memory

Future correction memory should store reviewed symbol decisions without pricing:

- category
- tag
- description
- template image path
- source name
- license status
- estimator notes
- source project id if safe

Do not store unit prices, bid strategy, markup, labor rates, or confidential notes in the shared repo.

## Licensing Caution

Reference sources such as public websites, standards PDFs, and blog posts can be useful for taxonomy and naming, but images should not be scraped or committed unless the license allows it and attribution requirements are preserved. When unsure, keep the asset private and mark it `verify_terms_before_commit` or `reference_only`.
