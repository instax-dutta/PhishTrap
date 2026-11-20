## Purpose

GitHub Actions automation for refreshing the Hugging Face dataset.

## Ownership

`.github/workflows/refresh-phishtrap.yml`.

## Local Contracts

- Cron `0 0 * * *` fires once daily at 00:00 UTC; `workflow_dispatch` accepts `force_full` and `max_samples`.
- The only secret is `HF_TOKEN`.
- The job needs `contents: write` for the final step that rewrites `Last dataset refresh:` in README.md. That commit is what keeps the repo active and prevents GitHub from disabling the cron after 60 days of inactivity.
- The concurrency group serializes runs; do not set `cancel-in-progress: true`.
- The pipeline step retries the whole run up to three times on transient failures, and a separate step verifies the upload.

## Work Guidance

- Keep the README timestamp line at column 0 with its exact `Last dataset refresh:` prefix; the workflow's `sed` matches on it.
- Any cadence change must also be reflected in README.md.

## Verification

- Workflow state: `gh api repos/instax-dutta/PhishTrap/actions/workflows --jq '.workflows[] | select(.name=="Refresh PhishTrap Dataset") | .state'`
- Manual run: `gh workflow run refresh-phishtrap.yml --repo instax-dutta/PhishTrap`

## Child DOX Index

No child DOX files.
