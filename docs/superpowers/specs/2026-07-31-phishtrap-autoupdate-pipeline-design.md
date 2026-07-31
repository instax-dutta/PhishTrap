# PhishTrap Auto-Update Pipeline

## Overview

Automated pipeline that refreshes the PhishTrap phishing URL dataset on a regular
cadence — pulling fresh phishing URLs from OpenPhish and other feeds, merging
with existing data, deduplicating, extracting features, rebalancing, and pushing
to Hugging Face.

## Architecture

### Pipeline trigger

GitHub Actions cron workflow that runs every 6 hours.

### Data sources

| Source | URL | Type | Update cadence |
|---|---|---|---|
| OpenPhish | `https://openphish.com/feed.txt` | Phishing URLs | Every 15 min |
| Phishing.Database | `https://phish.co.za/latest/ALL-phishing-domains.lst` | Phishing domains | Daily |
| PhishStats | `https://phishstats.info/phish.csv` | Phishing URLs | Hourly |
| Tranco Top 10K | `https://tranco-list.eu/download/Y8VQG/10000` | Legit domains | Weekly |
| Existing PhishTrap | Hugging Face `saidutta69/PhishTrap` | Full dataset | — |

### Pipeline stages

Each run executes these stages sequentially:

1. **Pull fresh data** — fetch phishing URLs from OpenPhish, Phishing.Database,
   PhishStats; fetch legit domains from Tranco.
2. **Pull existing PhishTrap** — download current dataset from HF `data/` folder.
3. **Merge & deduplicate** — combine new URLs with existing ones, deduplicate by
   URL key. Preserve provenance via `source` column.
4. **Extract 16 features** — same `extract_features()` logic from build script
   applied to any new URLs not already in the dataset.
5. **Rebalance** — stratified 50/50 split, target ~20K total samples, sample
   down majority if needed.
6. **Split** — 70/15/15 train/val/test.
7. **Upload to HF** — push CSV + Parquet files to `saidutta69/PhishTrap`.

### Key design decisions

- **No 15-min cadence for rebuilds.** The pipeline runs every 6 hours because
  feature extraction + balancing + upload takes non-trivial time and the GHA
  free tier has 6-hr concurrency limits. The feed is pulled fresh each run so no
  gap is missed.
- **URL-keyed dedup.** Deduplication uses the raw URL string as key (after
  lowercasing + stripping). If a URL already exists in PhishTrap, it is not
  re-added — its `source` field is updated to reflect new provenance.
- **Existing dataset is the seed.** On first run, if no HF dataset exists, it
  builds from scratch using the current `build_phishtrap.py` approach.
- **Incremental by default.** New URLs are appended; old ones are not removed
  unless explicitly pruned (future concern).
- **No model training in this phase.** Part 2 handles model training separately.
- **Resource-light.** GHA ubuntu-latest runner with Python is sufficient — no
  GPU needed.

### Files

| File | Purpose |
|---|---|
| `phishtrap_pipeline/__init__.py` | Package init |
| `phishtrap_pipeline/fetchers.py` | Functions to pull from each source |
| `phishtrap_pipeline/features.py` | Feature extraction (ported from build_phishtrap.py) |
| `phishtrap_pipeline/builder.py` | Merge, dedup, rebalance, split logic |
| `phishtrap_pipeline/uploader.py` | HF upload helpers |
| `phishtrap_pipeline/config.py` | Constants, sources, tokens |
| `phishtrap_pipeline/cli.py` | CLI entry point with argparse |
| `run_pipeline.py` | Top-level script called by GHA |
| `.github/workflows/refresh-phishtrap.yml` | GHA cron workflow |

### CLI interface

```text
python run_pipeline.py [--force-full] [--max-samples N]
  --force-full    Skip incremental merge, rebuild from scratch
  --max-samples   Max total samples per class (default 10000)
```

### Error handling

- Each fetcher is wrapped with retry (3 attempts, exponential backoff).
- If a source is unreachable, the pipeline logs a warning and continues with
  available sources — it does not fail entirely.
- Upload failure is retried once.
- Pipeline exits non-zero only if Hugging Face upload fails after retry.

### Security

- HF_TOKEN stored as GitHub Actions secret `HF_TOKEN`.
- No other secrets needed (all sources are public HTTP endpoints).
