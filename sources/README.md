# sources/ — Research Artifacts

This directory is the primary ingestion point for NotebookLM.

## Rules for this folder

- **Format:** Plain Markdown only (`.md`)
- **No scripts, no embeds, no interactive widgets** — machine-readable only
- **Naming:** `YYYY-MM-DD-[ASSET]-analysis.md`

## What goes here

- Central bank policy summaries
- Market structure analysis
- Sentiment reports
- Transcripts from research sources (YouTube, podcasts — converted to plain text)
- GitHub README excerpts relevant to your tooling
- Any document you've added to NotebookLM (keep a local copy here)

## Example files

```
2026-06-22-BTC-weekly-analysis.md
2026-06-22-GLOBAL-fed-rate-decision.md
2026-06-22-ETH-merge-staking-research.md
```

## NotebookLM sync

When you add a file here, also upload it to your NotebookLM notebook.
The agent queries NotebookLM — NotebookLM reads these source files.
Keep both in sync.
