---
license: mit
language: en
tags:
  - cybersecurity
  - phishing
  - url-detection
  - machine-learning
  - classification
  - security
size_categories:
  - 10K<n<100K
---

# PhishTrap

<div align="center">
  <img src="https://mirror.sdad.pro/racer_is_op_banaer_model_card_and_dataset_card.png" alt="RACER IS OP" width="100%">
</div>

<br>

> Catch phishing URLs before they catch you — 16 features, 19,954 URLs, balanced 50/50. Cross-verified from 496K phishing domains + Tranco top 10K. Automatically refreshed every 6 hours.

Priorities: **Quality > Ease of Access > Quantity**

**Build pipeline (open source):** [github.com/instax-dutta/PhishTrap](https://github.com/instax-dutta/PhishTrap) — see how every row is fetched, merged, deduplicated, validated and published.

---

## Dataset Overview

PhishTrap is a curated phishing URL detection dataset built for reproducibility. Every URL is either a confirmed phishing domain (from PyFunceble-verified feeds) or a top-ranked legitimate domain (from Tranco). Features are extracted from URL structure alone — no third-party lookups, no page content.

| Property | Value |
|---|---|
| Total Samples | 19,954 |
| Phishing URLs | 9,977 (50%) |
| Legitimate URLs | 9,977 (50%) |
| Features | 16 |
| Train/Val/Test | 70/15/15 |
| Formats | CSV, Parquet |
| License | MIT |

---

## Features

### Original 6 — URL Structure

| Feature | Description |
|---|---|
| `url_length` | Total URL character count |
| `hyphen_count` | Number of hyphens in URL |
| `digit_count` | Number of digits in URL |
| `subdomain_count` | Number of subdomains |
| `trusted_tld` | 1 if TLD is .com/.org/.net/.edu/.gov |
| `protocol_exists` | 1 if http/https present |

### Extended 10 — Deeper Signals

| Feature | Description |
|---|---|
| `special_char_count` | Count of special characters (@, -, _, ., etc.) |
| `entropy` | Shannon entropy of URL string |
| `path_depth` | Number of path segments |
| `domain_length` | Length of domain portion |
| `is_domain_ip` | 1 if domain is an IP address |
| `has_at_symbol` | 1 if @ present in URL |
| `has_double_slash_redirect` | 1 if // appears after protocol |
| `tld_length` | Length of top-level domain |
| `query_param_count` | Number of query parameters |
| `path_length` | Length of path portion |

---

## Data Sources

### Phishing URLs

| Source | Domains | Verification |
|---|---|---|
| Phishing.Database | 496,576 | PyFunceble-tested daily (MIT) |
| OpenPhish | 300+ (latest feed) | 15-min update cycle |

Phishing domains appear in at least one verified source. Domains are deduplicated across sources.

### Legitimate URLs

| Source | Domains | Why |
|---|---|---|
| Tranco top 10K | 10,000 | Aggregates CrUX + Cloudflare + Umbrella + Majestic |

Legitimate domains are filtered against the phishing set to remove any overlap.

---

## Label

- `0` = legitimate
- `1` = phishing

---

## Usage

### With Hugging Face Datasets

```python
from datasets import load_dataset

dataset = load_dataset("saidutta69/PhishTrap")
train = dataset["train"]
val = dataset["val"]
test = dataset["test"]

# Train a classifier
from sklearn.ensemble import RandomForestClassifier

X_train = train.select_columns([c for c in train.column_names if c not in ("url", "label", "source")])
y_train = train["label"]
X_test = test.select_columns([c for c in test.column_names if c not in ("url", "label", "source")])
y_test = test["label"]

clf = RandomForestClassifier(n_estimators=100, random_state=42)
clf.fit(X_train, y_train)
print(f"Accuracy: {clf.score(X_test, y_test):.4f}")
```

### With Pandas

```python
import pandas as pd

df = pd.read_csv("hf://datasets/saidutta69/PhishTrap/data/phishtrap_full.csv")
print(df.head())
```

---

## Auto-Update Pipeline

PhishTrap is continuously refreshed by an automated pipeline. The dataset is rebuilt every 6 hours with fresh phishing URLs from live feeds. The full pipeline is open source at [github.com/instax-dutta/PhishTrap](https://github.com/instax-dutta/PhishTrap).

### Architecture

```
GitHub Actions (cron, every 6h)
  │
  ├─ 1. Fetch phishing URLs  ── OpenPhish (15-min feed) + Phishing.Database + PhishStats
  ├─ 2. Fetch legit domains  ── Tranco top 10K
  ├─ 3. Merge with existing   ── canonical dedup (scheme/port/trailing-slash agnostic)
  ├─ 4. Prune expired         ── phishing URLs unconfirmed > 60 days are dropped
  ├─ 5. Extract 16 features   ── same feature set across all versions
  ├─ 6. Rebalance 50/50       ── stratified sampling
  ├─ 7. Split 70/15/15        ── train/val/test
  └─ 8. Validate + upload     ── pre-upload gates + post-upload verification → Hugging Face
```

### Quality guarantees

- **Freshness tracking** — every row carries `first_seen`, `last_seen`, and `collected_at` timestamps; consumers can tell how current each URL is
- **Canonical dedup** — `http://evil.com`, `https://evil.com/`, and `http://evil.com:80` collapse into one row via the `canonical_url` column
- **New evidence wins** — if a legitimate Tranco domain later appears in phishing feeds (e.g. it got compromised), the phishing label overrides it; label conflicts are logged
- **Expiry pruning** — phishing URLs unconfirmed for more than 60 days are removed automatically; legitimate domains never expire (Tranco top-10K is stable by design)
- **Provenance preserved** — the `source` column records every feed that reported a URL (e.g. `openphish+phishing_database`)
- **Source resilience** — 3 retries with exponential backoff per fetch; an unreachable source is skipped, never fatal
- **Pre-upload validation** — every split is checked for missing features, NaN/inf values, duplicates, and class balance before anything is uploaded
- **Post-upload verification** — after pushing, the pipeline downloads the uploaded files and re-validates them
- **Build metadata** — `data/dataset_info.json` records build ID, date, class/source distributions, and schema version
- **No partial state** — the full `data/` folder is replaced atomically per run

### Running the pipeline

```bash
export HF_TOKEN=hf_xxx          # required, from HF account settings
python run_pipeline.py          # incremental refresh
python run_pipeline.py --force-full    # rebuild from scratch
python run_pipeline.py --max-samples 20000   # bigger dataset
python run_pipeline.py --dry-run       # fetch/merge/prune/rebalance, no upload
```

### Manual trigger

The GitHub Actions workflow `Refresh PhishTrap Dataset` can also be triggered manually (workflow_dispatch) with optional `force_full` and `max_samples` inputs.

---

## Why PhishTrap?

Most phishing datasets throw URLs at you and call it a day. PhishTrap is different:

- **Cross-verified sources** — Every domain earns its place from reputable feeds
- **No data leakage** — Separate train/val/test splits with no overlap
- **Clean features** — 16 URL-based features, zero third-party API calls needed for inference
- **Reproducible** — Methodology is fully documented; re-run the pipeline anytime

---

## Citation

```bibtex
@misc{dash2026phishtrap,
  author = {Dash, Sai Dutta Abhishek and Sadangi, Jyotirmayi and
            Pradhan, Jatin Kumar and Sahoo, Bidush Kumar and Kumar, Raghvendra},
  title = {PhishTrap: High-Quality Phishing URL Dataset},
  year = {2026},
  publisher = {Hugging Face},
  howpublished = {\url{https://huggingface.co/datasets/saidutta69/PhishTrap}}
}
```

---

Built with Phishing.Database, OpenPhish, and Tranco. MIT licensed.
