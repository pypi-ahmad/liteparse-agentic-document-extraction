# Evaluate OCR accuracy

The evaluation command compares legacy single-read repair with consensus-based accuracy mode.
It uses a fixed 14-page suite and LandingAI ADE Markdown/JSON artifacts as the reference.

Evaluation consumes OpenAI API credits and writes source-derived text to disk. Confirm that the
corpus is permitted for local evaluation before running:

```powershell
uv run liteparse-ade-eval `
  --corpus-root "D:\AI\Github\OpenAI-Agentic-Document_extraction\data" `
  --acknowledge-sensitive-output
```

Results are written to a timestamped directory under `evaluation/runs/`. Each policy/document
directory contains candidate Markdown, candidate evidence JSON, and metrics. The root contains
`report.json`, a short `report.md`, and `artifacts.zip`.

The report includes normalized Markdown character error rate, table-cell F1, exact line-text F1,
repair counts, and consensus disagreements. LandingAI output is a comparison reference, not
perfect ground truth; inspect the per-document artifacts before interpreting small differences.

Use `--policies legacy` or `--policies accuracy` for a single-policy run. The command refuses to
write results unless `--acknowledge-sensitive-output` is present. `data/` and `evaluation/runs/`
are ignored by Git.
