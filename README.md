<img src="assets/banner.svg" alt="PhishTrap" width="100%">

# PhishTrap build pipeline

PhishTrap is a phishing URL detection dataset published on Hugging Face at `saidutta69/PhishTrap`. This repo holds the pipeline that builds and refreshes it: fetch from live threat feeds, extract 16 URL features, merge with the existing data, rebalance, split, validate, and upload.

Last dataset refresh: 2026-11-23T06:02:09Z

For feature definitions, data sources, splits, and usage examples, see the [dataset card on Hugging Face](https://huggingface.co/datasets/saidutta69/PhishTrap).

## Architecture

```
fetch live feeds -> merge with existing data -> prune stale evidence
    -> rebalance to 50/50 -> stratified split -> upload -> verify
```

The whole flow is driven by [`run_pipeline.py`](run_pipeline.py), which calls into the `phishtrap_pipeline` package. A GitHub Actions workflow runs it once a day at 00:00 UTC.

## Layout

| Path | Responsibility |
|---|---|
| `run_pipeline.py` | Orchestration and build metadata |
| `phishtrap_pipeline/fetchers.py` | Source fetching with retries and mirror fallbacks |
| `phishtrap_pipeline/features.py` | The 16 URL features |
| `phishtrap_pipeline/builder.py` | Canonical dedup, merge, expiry pruning, rebalance, split, validation |
| `phishtrap_pipeline/uploader.py` | Atomic writes, upload retries, post-upload verification |
| `phishtrap_pipeline/config.py` | Constants, source URLs, token lookup |
| `phishtrap_pipeline/cli.py` | `--force-full`, `--max-samples`, `--dry-run` |
| `tests/` | Unit tests for the pipeline modules |
| `.github/workflows/refresh-phishtrap.yml` | Scheduled refresh workflow |

The original single-file builder, `build_phishtrap.py`, is kept for reference. The package pipeline above is the supported path.

## Running locally

```bash
pip install -r requirements.txt
export HF_TOKEN=hf_...        # needed to upload; not needed for --dry-run

python3 run_pipeline.py --dry-run               # fetch, merge, rebalance, no upload
python3 run_pipeline.py                          # incremental refresh
python3 run_pipeline.py --force-full             # rebuild from scratch
python3 run_pipeline.py --max-samples 20000      # larger balanced dataset
```

## How updates work

Failed fetches retry with exponential backoff and fall back to mirror hosts; a source that is entirely unavailable is skipped rather than allowed to empty the dataset. Merging keys on a canonical URL that ignores scheme, default port, and trailing slash, so the same site reported in different formats collapses to one row. New evidence wins label conflicts, and phishing URLs unconfirmed for 60 days are pruned.

Every split is checked before publication for missing features, non-finite values, duplicate URLs, and class balance. After upload, the published files are downloaded and validated again.

The pipeline is deterministic: sampling is seeded, so the same inputs produce the same dataset.

## Scheduled refresh

The workflow retries the whole run up to three times on transient failures and then verifies the upload in a separate step. `HF_TOKEN` is its only secret. Runs are serialized through a concurrency group.

The final step rewrites the `Last dataset refresh:` line in this file and commits it. That commit is what keeps the repository active and prevents GitHub from disabling the cron after 60 days of inactivity. Do not reformat or indent that line.

## Verification

```bash
python3 -m pytest tests/ -q
python3 run_pipeline.py --dry-run
```

`pytest` is not currently declared in `requirements.txt`, so install it separately if it is missing.

Repo-level contracts and work guidance live in the `AGENTS.md` DOX tree.

## License

MIT.
