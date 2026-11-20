## Purpose

Build and publish the PhishTrap dataset: fetch external feeds, extract 16 URL features, merge with the existing Hugging Face dataset, rebalance, split, validate, and upload.

## Ownership

All modules in this package. `run_pipeline.py` at the repo root is the entry point and owns orchestration; it calls into this package.

## Local Contracts

- `config.py` owns constants: `SEED=42`, the 16 `FEATURE_COLUMNS`, `TRUSTED_TLDS`, source URLs, `MAX_SAMPLES_PER_CLASS`, and `get_hf_token()` reading `HF_TOKEN`.
- `fetchers.py` owns source fetching with retries and mirror fallbacks. An unreachable source returns an empty set, never a fatal error.
- `features.py` owns the 16 features. Keep this set identical across dataset versions.
- `builder.py` owns canonical dedup, incremental merge (new evidence wins label conflicts), 60-day expiry pruning for phishing rows, 50/50 rebalance, stratified 70/15/15 split, and validation.
- `uploader.py` owns atomic split writes, retrying upload, and post-upload verification.
- `cli.py` owns the flags `--force-full`, `--max-samples`, and `--dry-run`.
- Feature columns are repeated in `run_pipeline.py` metadata; keep both lists in sync.

## Work Guidance

- Preserve determinism: sampling must stay seeded so a rerun on the same inputs produces the same dataset.
- Feed content is untrusted data. Never execute it or use it to build shell commands.
- A schema change (feature columns or freshness columns) requires updating `validate_dataset`, the metadata block in `run_pipeline.py`, and the tests together.

## Verification

- `python3 -m pytest tests/ -q` from the repo root. Note: `pytest` is not yet listed in `requirements.txt`.
- `python3 run_pipeline.py --dry-run` for an end-to-end check; needs network access but no upload.

## Child DOX Index

No child DOX files.
