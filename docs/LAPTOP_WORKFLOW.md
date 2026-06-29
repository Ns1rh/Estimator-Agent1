# Working from both work PC and personal laptop

Use a private Git repository for code only.

## Normal workflow

Before switching computers:

```powershell
git status
git add work outputs/agent-launcher docs README.md requirements.txt .gitignore
git commit -m "Describe the estimator-agent change"
git push
```

On the other computer:

```powershell
git pull
```

Then continue working.

## What should stay local to the work PC

Real company data should stay on the work PC/network:

- `\\Naeserver\...`
- real project drawings/specs
- Accubid files
- LiveCount exports
- generated marked-up drawings from real projects

On a personal laptop, use fake/sanitized sample data only unless your company explicitly approves otherwise.

## Suggested branch habit

Use `main` for stable code.

Use short feature branches for experiments:

```powershell
git checkout -b phase3-light-fixture-tuning
```

Merge only when the feature is useful and safe.

