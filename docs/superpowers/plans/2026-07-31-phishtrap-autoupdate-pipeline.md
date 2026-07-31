# PhishTrap Auto-Update Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a secure, production-grade GitHub Actions pipeline that automatically refreshes the PhishTrap phishing URL dataset every 6 hours by pulling from multiple live feeds, merging with existing data, deduplicating, extracting features, rebalancing, and pushing to Hugging Face.

**Architecture:** A Python package (`phishtrap_pipeline/`) with separate modules for fetching, feature extraction, dataset building, and upload. A GitHub Actions cron workflow triggers `run_pipeline.py` every 6 hours. Every operation has retry logic, validation gates, and atomic upload with post-upload verification.

**Tech Stack:** Python 3.11, pandas, numpy, requests, huggingface_hub, tld, GitHub Actions

## Global Constraints

- HF_TOKEN must come from environment variable `HF_TOKEN` — never hardcoded
- Every external HTTP fetch: 3 retries with exponential backoff, 30s timeout per attempt
- Pre-upload validation must pass before any upload
- All splits must be balanced 50/50 (+/- 5%)
- No NaN, inf, or None values in any feature column
- Pipeline must not crash if a single source is unreachable (log and continue)
- Upload is atomic: push whole `data/` folder at once, never partial state
- Post-upload verification downloads and validates a sample row
- Every run creates a timestamped run log

---
### Task 1: Project scaffolding and config

**Files:**
- Create: `phishtrap_pipeline/__init__.py`
- Create: `phishtrap_pipeline/config.py`
- Create: `phishtrap_pipeline/cli.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Consumes: nothing
- Produces: `config.SOURCES`, `config.FEATURE_COLUMNS`, `config.SEED`, `config.OUTPUT_DIR`, CLI entry point

- [ ] **Step 1: Create `phishtrap_pipeline/__init__.py`**

```python
```

- [ ] **Step 2: Create `phishtrap_pipeline/config.py` with all constants**

```python
import os
from pathlib import Path

SEED = 42
HF_USER = "saidutta69"
DATASET_NAME = "PhishTrap"
REPO_ID = f"{HF_USER}/{DATASET_NAME}"

OUTPUT_DIR = Path("/tmp/phishtrap")
TEMP_DIR = OUTPUT_DIR / "_tmp"

FEATURE_COLUMNS = [
    "url_length", "hyphen_count", "digit_count", "subdomain_count",
    "trusted_tld", "protocol_exists", "special_char_count", "entropy",
    "path_depth", "domain_length", "is_domain_ip", "has_at_symbol",
    "has_double_slash_redirect", "tld_length", "query_param_count", "path_length",
]

TRUSTED_TLDS = {".com", ".org", ".net", ".edu", ".gov", ".mil", ".int"}

SOURCES = {
    "phishing_database": "https://phish.co.za/latest/ALL-phishing-domains.lst",
    "openphish": "https://openphish.com/feed.txt",
    "phishstats": "https://phishstats.info/phish.csv",
    "tranco": "https://tranco-list.eu/download/Y8VQG/10000",
}

MAX_SAMPLES_PER_CLASS = 10000

def get_hf_token():
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("HF_TOKEN environment variable not set")
    return token
```

- [ ] **Step 3: Create `phishtrap_pipeline/cli.py` with argparse**

```python
import argparse

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="PhishTrap dataset auto-update pipeline"
    )
    parser.add_argument(
        "--force-full",
        action="store_true",
        help="Skip incremental merge, rebuild from scratch",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=10000,
        help="Max total samples per class (default 10000)",
    )
    return parser.parse_args(argv)
```

---
### Task 2: Fetching module with secure retry logic

**Files:**
- Create: `phishtrap_pipeline/fetchers.py`
- Test: `tests/test_fetchers.py`

**Interfaces:**
- Consumes: `config.SOURCES`
- Produces: `fetch_url(url, retries=3) -> str`, `fetch_phishing_database() -> set[str]`, `fetch_openphish() -> set[str]`, `fetch_phishstats() -> set[str]`, `fetch_tranco(limit=10000) -> set[str]`, `fetch_all_sources() -> dict[str, set[str]]`

- [ ] **Step 1: Create `phishtrap_pipeline/fetchers.py`**

```python
import time
import logging
import requests

logger = logging.getLogger(__name__)

USER_AGENT = "PhishTrap-Pipeline/2.0"

def fetch_url(url, retries=3):
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, timeout=30,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_exc = e
            logger.warning("Fetch failed (attempt %d/%d) for %s: %s", attempt + 1, retries, url, e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    logger.error("All %d retries exhausted for %s: %s", retries, url, last_exc)
    raise last_exc

def fetch_phishing_database():
    text = fetch_url("https://phish.co.za/latest/ALL-phishing-domains.lst")
    domains = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            domains.add(line)
    return domains

def fetch_openphish():
    text = fetch_url("https://openphish.com/feed.txt")
    urls = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line:
            urls.add(line)
    return urls

def fetch_phishstats():
    text = fetch_url("https://phishstats.info/phish.csv")
    urls = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) >= 4:
            url = parts[3].strip().strip('"')
            if url:
                urls.add(url)
    return urls

def fetch_tranco(limit=10000):
    text = fetch_url("https://tranco-list.eu/download/Y8VQG/10000")
    domains = []
    for line in text.strip().splitlines():
        parts = line.strip().split(",")
        domain = parts[1].strip().lower() if len(parts) >= 2 else parts[0].strip().lower()
        domains.append(domain)
        if len(domains) >= limit:
            break
    return set(domains)

def fetch_all_sources():
    results = {}
    sources = [
        ("phishing_database", fetch_phishing_database),
        ("openphish", fetch_openphish),
        ("phishstats", fetch_phishstats),
        ("tranco", fetch_tranco),
    ]
    for name, fn in sources:
        try:
            data = fn()
            results[name] = data
            logger.info("Fetched %d items from %s", len(data), name)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", name, e)
            results[name] = set()
    return results
```

- [ ] **Step 2: Create `tests/test_fetchers.py`**

```python
import pytest
import responses
from phishtrap_pipeline import fetchers

@responses.activate
def test_fetch_url_success():
    responses.add(responses.GET, "http://example.com/feed.txt", body="a.com\nb.com\n", status=200)
    text = fetchers.fetch_url("http://example.com/feed.txt", retries=1)
    assert "a.com" in text

@responses.activate
def test_fetch_url_retries_on_failure():
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", body="ok\n", status=200)
    text = fetchers.fetch_url("http://example.com/feed.txt", retries=3)
    assert text == "ok\n"

@responses.activate
def test_fetch_url_exhausts_retries():
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    with pytest.raises(Exception):
        fetchers.fetch_url("http://example.com/feed.txt", retries=3)

@responses.activate
def test_fetch_openphish():
    responses.add(responses.GET, "https://openphish.com/feed.txt", body="http://evil.com/login\nhttp://bad.com\n", status=200)
    urls = fetchers.fetch_openphish()
    assert "http://evil.com/login" in urls
    assert "http://bad.com" in urls
    assert len(urls) == 2

@responses.activate
def test_fetch_tranco():
    csv_data = "1,google.com\n2,facebook.com\n3,youtube.com\n"
    responses.add(responses.GET, "https://tranco-list.eu/download/Y8VQG/10000", body=csv_data, status=200)
    domains = fetchers.fetch_tranco(limit=3)
    assert domains == {"google.com", "facebook.com", "youtube.com"}

@responses.activate
def test_fetch_all_sources_partial_failure():
    responses.add(responses.GET, "https://phish.co.za/latest/ALL-phishing-domains.lst", body="evil.com\n", status=200)
    responses.add(responses.GET, "https://openphish.com/feed.txt", status=500)  # fails
    responses.add(responses.GET, "https://phishstats.info/phish.csv", status=500)  # fails
    responses.add(responses.GET, "https://tranco-list.eu/download/Y8VQG/10000", body="1,good.com\n", status=200)
    results = fetchers.fetch_all_sources()
    assert "evil.com" in results["phishing_database"]
    assert results["openphish"] == set()
    assert results["phishstats"] == set()
    assert "good.com" in results["tranco"]
```

- [ ] **Step 3: Run tests**

```bash
pip install pytest responses && python -m pytest tests/test_fetchers.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add phishtrap_pipeline/ tests/test_fetchers.py
git commit -m "feat: add fetching module with retry logic and tests"
```

---
### Task 3: Feature extraction module

**Files:**
- Create: `phishtrap_pipeline/features.py`
- Test: `tests/test_features.py`

**Interfaces:**
- Consumes: `config.FEATURE_COLUMNS`, `config.TRUSTED_TLDS`
- Produces: `extract_features(url: str) -> dict`, `compute_entropy(s: str) -> float`, `extract_domain_from_url(url: str) -> str`, `extract_url_features(urls: set, label: int, source: str) -> list[dict]`

- [ ] **Step 1: Create `phishtrap_pipeline/features.py`**

```python
import math
import re
from urllib.parse import urlparse

from tld import get_tld

from phishtrap_pipeline.config import TRUSTED_TLDS


def compute_entropy(s):
    if not s:
        return 0.0
    prob = [s.count(c) / len(s) for c in set(s)]
    return -sum(p * math.log2(p) for p in prob)


def extract_domain_from_url(url):
    try:
        if url.startswith("http"):
            parsed = urlparse(url)
            return parsed.netloc.lower()
        return url.lower().strip()
    except Exception:
        return url.lower().strip()


def extract_features(url):
    url_str = str(url).lower().strip()
    if not url_str.startswith("http"):
        url_str = "http://" + url_str
    parsed = urlparse(url_str)

    hostname = parsed.hostname or ""
    path = parsed.path or ""

    features = {}
    features["url_length"] = len(url_str)
    features["hyphen_count"] = url_str.count("-")
    features["digit_count"] = sum(1 for c in url_str if c.isdigit())
    features["subdomain_count"] = max(0, len(hostname.split(".")) - 2)

    try:
        tld_info = get_tld(url_str, fail_silently=True)
        features["trusted_tld"] = 1 if tld_info and f".{tld_info}" in TRUSTED_TLDS else 0
    except Exception:
        features["trusted_tld"] = 0

    features["protocol_exists"] = 1 if re.match(r"^https?://", str(url).lower().strip()) else 0
    features["special_char_count"] = sum(1 for c in url_str if c in "@-_.,;:#~!$&'()*+/:=?")
    features["entropy"] = compute_entropy(url_str)
    features["path_depth"] = len([p for p in path.split("/") if p])
    features["domain_length"] = len(hostname)
    features["is_domain_ip"] = 1 if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname) else 0
    features["has_at_symbol"] = 1 if "@" in url_str else 0
    features["has_double_slash_redirect"] = 1 if url_str.count("//") > 1 else 0

    try:
        tld_part = get_tld(url_str, fail_silently=True)
        features["tld_length"] = len(tld_part) if tld_part else 0
    except Exception:
        features["tld_length"] = 0

    features["query_param_count"] = len(parsed.query.split("&")) if parsed.query else 0
    features["path_length"] = len(path)
    return features


def extract_url_features(urls, label, source_tag):
    rows = []
    for url in urls:
        try:
            feats = extract_features(url)
            feats["url"] = url
            feats["label"] = label
            feats["source"] = source_tag
            rows.append(feats)
        except Exception:
            continue
    return rows
```

- [ ] **Step 2: Create `tests/test_features.py`**

```python
import pytest
from phishtrap_pipeline.features import (
    extract_features,
    compute_entropy,
    extract_domain_from_url,
    extract_url_features,
)


class TestComputeEntropy:
    def test_empty_string(self):
        assert compute_entropy("") == 0.0

    def test_single_char(self):
        assert compute_entropy("aaa") == 0.0

    def test_uniform_distribution(self):
        e = compute_entropy("ab")
        assert e == 1.0


class TestExtractDomainFromUrl:
    def test_http_url(self):
        assert extract_domain_from_url("http://evil.com/login") == "evil.com"

    def test_domain_only(self):
        assert extract_domain_from_url("evil.com") == "evil.com"

    def test_with_www(self):
        assert extract_domain_from_url("https://www.google.com/search") == "www.google.com"


class TestExtractFeatures:
    def test_normal_url(self):
        feats = extract_features("https://google.com/search")
        assert feats["url_length"] > 0
        assert feats["protocol_exists"] == 1
        assert feats["trusted_tld"] == 1
        assert feats["has_at_symbol"] == 0

    def test_phishy_url(self):
        feats = extract_features("http://login-verify-paypal.secure-login.evil.com/@phishing")
        assert feats["hyphen_count"] > 0
        assert feats["has_at_symbol"] == 1
        assert feats["subdomain_count"] >= 3

    def test_ip_url(self):
        feats = extract_features("http://192.168.1.1/login")
        assert feats["is_domain_ip"] == 1

    def test_all_feature_columns_present(self):
        from phishtrap_pipeline.config import FEATURE_COLUMNS
        feats = extract_features("https://example.com")
        for col in FEATURE_COLUMNS:
            assert col in feats, f"Missing feature: {col}"

    def test_no_nan_values(self):
        import math
        feats = extract_features("https://example.com/path?q=1&r=2")
        for k, v in feats.items():
            if isinstance(v, float):
                assert not math.isnan(v), f"NaN in {k}"
                assert not math.isinf(v), f"Inf in {k}"


class TestExtractUrlFeatures:
    def test_extracts_multiple_urls(self):
        urls = {"http://evil.com", "http://good.com"}
        rows = extract_url_features(urls, 1, "test")
        assert len(rows) == 2
        for row in rows:
            assert row["label"] == 1
            assert row["source"] == "test"
```

- [ ] **Step 3: Run tests**

```bash
pip install tld && python -m pytest tests/test_features.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add phishtrap_pipeline/features.py tests/test_features.py
git commit -m "feat: add feature extraction module with entropy and URL parsing"
```

---
### Task 4: Dataset builder with merge, dedup, rebalance, and validation

**Files:**
- Create: `phishtrap_pipeline/builder.py`
- Test: `tests/test_builder.py`

**Interfaces:**
- Consumes: `config.FEATURE_COLUMNS`, `config.SEED`, `config.MAX_SAMPLES_PER_CLASS`, `extract_features()` from Task 2
- Produces: `validate_dataset(df) -> None` (raises on invalid), `merge_with_existing(new_rows, existing_df=None) -> pd.DataFrame`, `rebalance(df, max_per_class=10000) -> pd.DataFrame`, `split_dataset(df) -> dict[str, pd.DataFrame]`, `build_pipeline(source_data: dict, force_full: bool, max_samples: int) -> pd.DataFrame`

- [ ] **Step 1: Create `phishtrap_pipeline/builder.py`**

```python
import logging
import math
import random

import numpy as np
import pandas as pd

from phishtrap_pipeline.config import FEATURE_COLUMNS, SEED

logger = logging.getLogger(__name__)


class DatasetValidationError(ValueError):
    pass


def validate_dataset(df):
    errors = []

    if df.empty:
        raise DatasetValidationError("Dataset is empty")

    for col in FEATURE_COLUMNS:
        if col not in df.columns:
            errors.append(f"Missing feature column: {col}")
            continue
        null_count = df[col].isnull().sum()
        if null_count > 0:
            errors.append(f"Column {col} has {null_count} null values")
        if df[col].dtype.kind == "f":
            inf_count = np.isinf(df[col]).sum()
            if inf_count > 0:
                errors.append(f"Column {col} has {inf_count} inf values")

    if "label" in df.columns:
        counts = df["label"].value_counts()
        if len(counts) != 2:
            errors.append(f"Expected 2 classes, got {len(counts)}")
        else:
            ratio = counts[0] / counts[1]
            if ratio < 0.9 or ratio > 1.1:
                errors.append(f"Class imbalance: {counts.to_dict()} (ratio={ratio:.3f})")

    if "url" in df.columns:
        dups = df["url"].duplicated().sum()
        if dups > 0:
            errors.append(f"Found {dups} duplicate URLs")

    if errors:
        raise DatasetValidationError("; ".join(errors))


def merge_with_existing(new_rows, existing_df=None):
    if not new_rows:
        logger.warning("No new rows to add")
        return existing_df

    new_df = pd.DataFrame(new_rows)

    if existing_df is None or existing_df.empty:
        logger.info("No existing dataset, returning new data")
        return new_df

    existing_urls = set(existing_df["url"].str.lower().str.strip())
    new_df = new_df[~new_df["url"].str.lower().str.strip().isin(existing_urls)].copy()
    logger.info("New unique URLs after dedup: %d out of %d", len(new_df), len(new_rows))

    if new_df.empty:
        logger.info("No new URLs to add")
        return existing_df

    merged = pd.concat([existing_df, new_df], ignore_index=True)
    merged = merged.drop_duplicates(subset=["url"], keep="first")
    logger.info("Merged dataset size: %d", len(merged))
    return merged


def rebalance(df, max_per_class=10000):
    random.seed(SEED)
    np.random.seed(SEED)

    phishing = df[df["label"] == 1]
    legit = df[df["label"] == 0]

    n = min(len(phishing), len(legit), max_per_class)
    logger.info("Rebalancing to %d per class (phishing=%d, legit=%d)", n, len(phishing), len(legit))

    phishing_sample = phishing.sample(n=n, random_state=SEED)
    legit_sample = legit.sample(n=n, random_state=SEED)

    balanced = pd.concat([phishing_sample, legit_sample], ignore_index=True)
    balanced = balanced.sample(frac=1, random_state=SEED).reset_index(drop=True)
    return balanced


def split_dataset(df):
    train = df.sample(frac=0.7, random_state=SEED)
    remaining = df.drop(train.index)
    val = remaining.sample(frac=0.5, random_state=SEED)
    test = remaining.drop(val.index)
    return {"train": train, "val": val, "test": test}
```

- [ ] **Step 2: Create `tests/test_builder.py`**

```python
import pytest
import pandas as pd
import numpy as np
from phishtrap_pipeline.builder import (
    validate_dataset,
    DatasetValidationError,
    merge_with_existing,
    rebalance,
    split_dataset,
)
from phishtrap_pipeline.config import FEATURE_COLUMNS


def _make_valid_df(n=100):
    rows = []
    for i in range(n):
        row = {col: 0 for col in FEATURE_COLUMNS}
        row["url"] = f"http://example{i}.com"
        row["label"] = i % 2
        row["source"] = "test"
        rows.append(row)
    return pd.DataFrame(rows)


class TestValidateDataset:
    def test_valid_dataset_passes(self):
        df = _make_valid_df()
        validate_dataset(df)

    def test_empty_dataset_raises(self):
        with pytest.raises(DatasetValidationError):
            validate_dataset(pd.DataFrame())

    def test_missing_feature_raises(self):
        df = _make_valid_df()
        df = df.drop(columns=["entropy"])
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)

    def test_nan_feature_raises(self):
        df = _make_valid_df()
        df.loc[0, "url_length"] = np.nan
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)

    def test_imbalanced_classes_raises(self):
        df = _make_valid_df()
        df["label"] = 0
        df.iloc[0, df.columns.get_loc("label")] = 1
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)

    def test_duplicate_urls_raises(self):
        df = _make_valid_df()
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)


class TestMergeWithExisting:
    def test_merges_new_urls(self):
        existing = pd.DataFrame({
            "url": ["http://a.com"],
            "url_length": [10], "label": [1], "source": ["old"],
            **{col: [0] for col in FEATURE_COLUMNS[1:]},
        })
        new_row = {
            "url": "http://b.com", "url_length": 10, "label": 0, "source": "new",
            **{col: 0 for col in FEATURE_COLUMNS[1:]},
        }
        merged = merge_with_existing([new_row], existing)
        assert len(merged) == 2

    def test_deduplicates_existing_urls(self):
        existing = pd.DataFrame({
            "url": ["http://a.com"],
            "url_length": [10], "label": [1], "source": ["old"],
            **{col: [0] for col in FEATURE_COLUMNS[1:]},
        })
        dup_row = {
            "url": "http://a.com", "url_length": 10, "label": 0, "source": "new",
            **{col: 0 for col in FEATURE_COLUMNS[1:]},
        }
        merged = merge_with_existing([dup_row], existing)
        assert len(merged) == 1

    def test_returns_existing_when_no_new(self):
        existing = _make_valid_df(10)
        merged = merge_with_existing([], existing)
        assert len(merged) == 10


class TestRebalance:
    def test_balanced_output(self):
        phishing = pd.DataFrame({
            **{col: [0] * 100 for col in FEATURE_COLUMNS},
            "url": [f"http://evil{i}.com" for i in range(100)],
            "label": [1] * 100,
            "source": ["test"] * 100,
        })
        legit = pd.DataFrame({
            **{col: [0] * 50 for col in FEATURE_COLUMNS},
            "url": [f"http://good{i}.com" for i in range(50)],
            "label": [0] * 50,
            "source": ["test"] * 50,
        })
        df = pd.concat([phishing, legit], ignore_index=True)
        balanced = rebalance(df, max_per_class=50)
        assert balanced["label"].value_counts().to_dict() == {0: 50, 1: 50}

    def test_respects_max_per_class(self):
        phishing = pd.DataFrame({
            **{col: [0] * 200 for col in FEATURE_COLUMNS},
            "url": [f"http://evil{i}.com" for i in range(200)],
            "label": [1] * 200,
            "source": ["test"] * 200,
        })
        legit = pd.DataFrame({
            **{col: [0] * 200 for col in FEATURE_COLUMNS},
            "url": [f"http://good{i}.com" for i in range(200)],
            "label": [0] * 200,
            "source": ["test"] * 200,
        })
        df = pd.concat([phishing, legit], ignore_index=True)
        balanced = rebalance(df, max_per_class=50)
        assert len(balanced) == 100
        assert balanced["label"].value_counts().to_dict() == {0: 50, 1: 50}


class TestSplitDataset:
    def test_splits_70_15_15(self):
        df = _make_valid_df(1000)
        splits = split_dataset(df)
        assert "train" in splits and "val" in splits and "test" in splits
        assert len(splits["train"]) == 700
        assert len(splits["val"]) == 150
        assert len(splits["test"]) == 150

    def test_no_overlap(self):
        df = _make_valid_df(1000)
        splits = split_dataset(df)
        train_urls = set(splits["train"]["url"])
        val_urls = set(splits["val"]["url"])
        test_urls = set(splits["test"]["url"])
        assert train_urls.isdisjoint(val_urls)
        assert train_urls.isdisjoint(test_urls)
        assert val_urls.isdisjoint(test_urls)
```

- [ ] **Step 3: Run tests**

```bash
python -m pytest tests/test_builder.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add phishtrap_pipeline/builder.py tests/test_builder.py
git commit -m "feat: add dataset builder with merge, dedup, rebalance, split, and validation"
```

---
### Task 5: Hugging Face uploader with pre-upload validation and post-upload verification

**Files:**
- Create: `phishtrap_pipeline/uploader.py`
- Test: `tests/test_uploader.py`

**Interfaces:**
- Consumes: `config.REPO_ID`, `config.get_hf_token()`
- Produces: `upload_dataset(splits: dict, output_dir: Path) -> str`, `verify_upload(repo_id: str) -> bool`

- [ ] **Step 1: Create `phishtrap_pipeline/uploader.py`**

```python
import logging
import shutil
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi, upload_folder

from phishtrap_pipeline.config import HF_USER, DATASET_NAME, REPO_ID, get_hf_token
from phishtrap_pipeline.builder import validate_dataset

logger = logging.getLogger(__name__)


def _save_splits(splits, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, split_df in splits.items():
        validate_dataset(split_df)
        csv_path = output_dir / f"{name}.csv"
        parquet_path = output_dir / f"{name}.parquet"
        split_df.to_csv(csv_path, index=False)
        split_df.to_parquet(parquet_path, index=False)
        logger.info("Saved %s: %d rows (csv+parquet)", name, len(split_df))

    # Also save full dataset
    full = pd.concat(splits.values(), ignore_index=True)
    validate_dataset(full)
    full.to_csv(output_dir / "phishtrap_full.csv", index=False)
    full.to_parquet(output_dir / "phishtrap_full.parquet", index=False)
    logger.info("Saved full dataset: %d rows", len(full))


def upload_dataset(splits, output_dir):
    token = get_hf_token()
    api = HfApi(token=token)

    _save_splits(splits, output_dir)

    logger.info("Ensuring repo %s exists...", REPO_ID)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)

    logger.info("Uploading data/ folder to %s...", REPO_ID)
    upload_folder(
        folder_path=str(output_dir),
        repo_id=REPO_ID,
        repo_type="dataset",
        token=token,
        path_in_repo="data",
    )

    repo_url = f"https://huggingface.co/datasets/{REPO_ID}"
    logger.info("Upload complete: %s", repo_url)
    return repo_url


def verify_upload(repo_id=None):
    token = get_hf_token()
    api = HfApi(token=token)
    repo_id = repo_id or REPO_ID

    try:
        files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
        required = [
            "data/train.csv", "data/val.csv", "data/test.csv",
            "data/train.parquet", "data/val.parquet", "data/test.parquet",
        ]
        for f in required:
            if f not in files:
                logger.error("Verification failed: missing %s", f)
                return False

        train = api.hf_hub_download(repo_id=repo_id, repo_type="dataset", filename="data/train.csv")
        df = pd.read_csv(train)
        validate_dataset(df)
        logger.info("Verification passed: %d rows in train split", len(df))
        return True
    except Exception as e:
        logger.error("Verification failed: %s", e)
        return False
```

- [ ] **Step 2: Create `tests/test_uploader.py`**

```python
import pytest
import pandas as pd
from pathlib import Path
from phishtrap_pipeline.uploader import _save_splits
from phishtrap_pipeline.config import FEATURE_COLUMNS


def _make_split_df(n=100, label=0):
    return pd.DataFrame({
        **{col: [0] * n for col in FEATURE_COLUMNS},
        "url": [f"http://example{i}.com" for i in range(n)],
        "label": [label] * n,
        "source": ["test"] * n,
    })


def test_save_splits_creates_files(tmp_path):
    splits = {
        "train": _make_split_df(70, label=0),
        "val": _make_split_df(15, label=0),
        "test": _make_split_df(15, label=0),
    }
    _save_splits(splits, tmp_path)
    assert (tmp_path / "train.csv").exists()
    assert (tmp_path / "val.csv").exists()
    assert (tmp_path / "test.csv").exists()
    assert (tmp_path / "train.parquet").exists()
    assert (tmp_path / "val.parquet").exists()
    assert (tmp_path / "test.parquet").exists()
    assert (tmp_path / "phishtrap_full.csv").exists()
    assert (tmp_path / "phishtrap_full.parquet").exists()


def test_save_splits_validates(tmp_path):
    bad_df = pd.DataFrame({"bad_col": [1, 2]})
    with pytest.raises(Exception):
        _save_splits({"train": bad_df}, tmp_path)
```

- [ ] **Step 3: Run tests**

```bash
pip install huggingface_hub && python -m pytest tests/test_uploader.py -v
```

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add phishtrap_pipeline/uploader.py tests/test_uploader.py
git commit -m "feat: add HF uploader with validation gates and post-upload verification"
```

---
### Task 6: Pipeline CLI entry point

**Files:**
- Create: `run_pipeline.py`

**Interfaces:**
- Consumes: All tasks above
- Produces: Top-level entry point called by GHA

- [ ] **Step 1: Create `run_pipeline.py`**

```python
#!/usr/bin/env python3
"""
PhishTrap auto-update pipeline entry point.
Called by GitHub Actions cron workflow.
"""
import logging
import sys
from pathlib import Path

from phishtrap_pipeline.config import OUTPUT_DIR, TEMP_DIR, MAX_SAMPLES_PER_CLASS, get_hf_token
from phishtrap_pipeline.fetchers import fetch_all_sources
from phishtrap_pipeline.features import extract_url_features, extract_domain_from_url
from phishtrap_pipeline.builder import (
    merge_with_existing,
    rebalance,
    split_dataset,
    validate_dataset,
)
from phishtrap_pipeline.uploader import upload_dataset, verify_upload
from phishtrap_pipeline.cli import parse_args


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("phishtrap.pipeline")


def download_existing_dataset():
    from huggingface_hub import HfApi
    from phishtrap_pipeline.config import REPO_ID
    token = get_hf_token()
    api = HfApi(token=token)
    try:
        files = api.list_repo_files(repo_id=REPO_ID, repo_type="dataset")
        if "data/phishtrap_full.csv" in files:
            import pandas as pd
            csv_path = api.hf_hub_download(
                repo_id=REPO_ID, repo_type="dataset", filename="data/phishtrap_full.csv"
            )
            df = pd.read_csv(csv_path)
            logger.info("Downloaded existing dataset: %d rows", len(df))
            return df
    except Exception as e:
        logger.warning("Could not download existing dataset: %s", e)
    return None


def main():
    args = parse_args()
    logger.info("Starting PhishTrap pipeline (force_full=%s, max_samples=%d)", args.force_full, args.max_samples)

    # Step 1: Fetch fresh data from all sources
    logger.info("Step 1: Fetching data from sources...")
    source_data = fetch_all_sources()

    # Step 2: Build phishing set
    phishing_urls = set()
    for key in ("phishing_database", "openphish", "phishstats"):
        for item in source_data.get(key, set()):
            url = item if item.startswith("http") else f"http://{item}"
            phishing_urls.add(url)
    logger.info("Total phishing URLs: %d", len(phishing_urls))

    legit_domains = source_data.get("tranco", set())
    legit_domains = legit_domains - {extract_domain_from_url(u) for u in phishing_urls}
    legit_urls = {f"http://{d}" for d in legit_domains}
    logger.info("Total legit URLs: %d", len(legit_urls))

    # Step 3: Extract features
    logger.info("Step 2: Extracting features...")
    phishing_rows = extract_url_features(phishing_urls, label=1, source="live_feed")
    legit_rows = extract_url_features(legit_urls, label=0, source="tranco")
    logger.info("Phishing rows: %d, Legit rows: %d", len(phishing_rows), len(legit_rows))

    if not phishing_rows or not legit_rows:
        logger.error("No data extracted from sources, aborting")
        sys.exit(1)

    # Step 4: Merge with existing
    logger.info("Step 3: Merging with existing dataset...")
    if args.force_full:
        existing = None
    else:
        existing = download_existing_dataset()

    all_new = phishing_rows + legit_rows
    merged = merge_with_existing(all_new, existing)

    if merged is None or merged.empty:
        logger.error("Merge produced empty dataset, aborting")
        sys.exit(1)

    # Step 5: Rebalance
    logger.info("Step 4: Rebalancing...")
    balanced = rebalance(merged, max_per_class=args.max_samples)
    validate_dataset(balanced)
    logger.info("Balanced dataset: %d rows", len(balanced))

    # Step 6: Split
    logger.info("Step 5: Splitting...")
    splits = split_dataset(balanced)
    for name, split_df in splits.items():
        logger.info("  %s: %d rows", name, len(split_df))

    # Step 7: Upload
    logger.info("Step 6: Uploading to Hugging Face...")
    repo_url = upload_dataset(splits, OUTPUT_DIR / "data")
    logger.info("Uploaded to %s", repo_url)

    # Step 8: Verify
    logger.info("Step 7: Verifying upload...")
    if verify_upload():
        logger.info("Pipeline completed successfully!")
    else:
        logger.error("Post-upload verification FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Dry-run test (manual verification that imports work)**

```bash
python -c "from phishtrap_pipeline import cli, config, fetchers, features, builder, uploader; print('All imports OK')"
```

- [ ] **Step 3: Commit**

```bash
git add run_pipeline.py
git commit -m "feat: add pipeline entry point with full orchestration"
```

---
### Task 7: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/refresh-phishtrap.yml`

**Interfaces:**
- Consumes: `run_pipeline.py` from Task 6
- Produces: Scheduled pipeline execution every 6 hours

- [ ] **Step 1: Create `.github/workflows/refresh-phishtrap.yml`**

```yaml
name: Refresh PhishTrap Dataset

on:
  schedule:
    - cron: '0 */6 * * *'
  workflow_dispatch:
    inputs:
      force_full:
        description: 'Force full rebuild from scratch'
        required: false
        type: boolean
        default: false
      max_samples:
        description: 'Max samples per class'
        required: false
        type: number
        default: 10000

env:
  HF_TOKEN: ${{ secrets.HF_TOKEN }}

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip

      - name: Install dependencies
        run: |
          pip install --upgrade pip
          pip install pandas numpy requests huggingface_hub tld

      - name: Run PhishTrap pipeline
        run: |
          ARGS=""
          if [[ "${{ github.event_name }}" == "workflow_dispatch" ]]; then
            if [[ "${{ github.event.inputs.force_full }}" == "true" ]]; then
              ARGS="$ARGS --force-full"
            fi
            ARGS="$ARGS --max-samples ${{ github.event.inputs.max_samples }}"
          fi
          python run_pipeline.py $ARGS

      - name: Verify upload
        run: |
          python -c "
from phishtrap_pipeline.uploader import verify_upload
assert verify_upload(), 'Post-upload verification failed'
print('Verification passed')
"
```

- [ ] **Step 2: Verify GHA syntax**

```bash
pip install yamllint && yamllint .github/workflows/refresh-phishtrap.yml
```

Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/refresh-phishtrap.yml
git commit -m "ci: add GitHub Actions cron workflow for PhishTrap auto-refresh"
```

---
### Task 8: Requirements file and README update

**Files:**
- Create: `requirements.txt`
- Modify: `README.md`

- [ ] **Step 1: Create `requirements.txt`**

```txt
pandas>=2.0.0
numpy>=1.24.0
requests>=2.31.0
huggingface_hub>=0.20.0
tld>=0.13
```

- [ ] **Step 2: Update README.md with pipeline usage and architecture**

Update the existing README.md to add a section on the auto-update pipeline, architecture, and how to trigger manual runs.

- [ ] **Step 3: Commit**

```bash
git add requirements.txt README.md
git commit -m "docs: add requirements.txt and pipeline documentation"
```

---
### Task 9: Integration test (end-to-end dry run)

- [ ] **Step 1: Run full test suite**

```bash
pip install -r requirements.txt && pip install pytest responses && python -m pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 2: Verify pipeline imports work end-to-end**

```bash
python -c "
from phishtrap_pipeline.cli import parse_args
from phishtrap_pipeline.config import FEATURE_COLUMNS, SOURCES
from phishtrap_pipeline.fetchers import fetch_url
from phishtrap_pipeline.features import extract_features
from phishtrap_pipeline.builder import validate_dataset, rebalance, split_dataset
from phishtrap_pipeline.uploader import verify_upload
print('End-to-end import check: OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: finalize pipeline with complete test coverage"
```
