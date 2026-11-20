## Purpose

Unit tests for the pipeline modules.

## Ownership

The `test_*.py` modules in this folder. Each targets one pipeline module: `test_builder`, `test_features`, `test_fetchers`, `test_uploader`.

## Local Contracts

- Tests use `pytest` and must not require network access or a real Hugging Face upload.
- Fixtures should build small in-memory DataFrames rather than reading published dataset files.

## Work Guidance

- When changing a pipeline module, add or update the matching test module in the same change.
- Test validation boundaries: missing columns, nulls, imbalance, duplicate canonical URLs, and malformed feed input.

## Verification

- `python3 -m pytest tests/ -q` from the repo root. Add `pytest` to `requirements.txt` if the environment does not already provide it.

## Child DOX Index

No child DOX files.
