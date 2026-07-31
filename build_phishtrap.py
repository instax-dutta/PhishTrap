import hashlib
import csv
import math
import os
import random
import re
import tarfile
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import requests
from huggingface_hub import HfApi, upload_folder
from tld import get_tld

SEED = 42
random.seed(SEED)
np.random.seed(SEED)

HF_TOKEN = "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"
HF_USER = "saidutta69"
DATASET_NAME = "PhishTrap"

OUTPUT_DIR = Path("/tmp/phishtrap")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PHISHING_SOURCES = {
    "phishing_database": "https://phish.co.za/latest/ALL-phishing-domains.lst",
    "openphish": "https://openphish.com/feed.txt",
    "phishtank": None,  # Will use snapshot if available
}

LEGIT_SOURCE = "https://tranco-list.eu/download/Y8VQG/10000"

TRUSTED_TLDS = {".com", ".org", ".net", ".edu", ".gov", ".mil", ".int"}


def fetch_url(url, retries=3):
    for i in range(retries):
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "PhishTrap/1.0"})
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 ** i)


def download_phishing_database():
    text = fetch_url(PHISHING_SOURCES["phishing_database"])
    domains = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            domains.add(line)
    return domains


def download_openphish():
    text = fetch_url(PHISHING_SOURCES["openphish"])
    urls = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line:
            urls.add(line)
    return urls


def download_tranco(limit=10000):
    text = fetch_url(LEGIT_SOURCE)
    domains = []
    for line in text.strip().splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 2:
            domains.append(parts[1].strip().lower())
        elif parts:
            domains.append(parts[0].strip().lower())
        if len(domains) >= limit:
            break
    return set(domains)


def extract_domain_from_url(url):
    try:
        if url.startswith("http"):
            parsed = urlparse(url)
            return parsed.netloc.lower()
        return url.lower().strip()
    except Exception:
        return url.lower().strip()


def extract_features(url):
    features = {}
    url_str = str(url).lower().strip()
    parsed = urlparse(url_str if url_str.startswith("http") else "http://" + url_str)

    features["url_length"] = len(url_str)
    features["hyphen_count"] = url_str.count("-")
    features["digit_count"] = sum(1 for c in url_str if c.isdigit())
    features["subdomain_count"] = len(parsed.hostname.split(".")) - 2 if parsed.hostname and len(parsed.hostname.split(".")) > 2 else 0

    try:
        tld_info = get_tld(url_str, fail_silently=True)
        features["trusted_tld"] = 1 if tld_info and f".{tld_info}" in TRUSTED_TLDS else 0
    except Exception:
        features["trusted_tld"] = 0

    features["protocol_exists"] = 1 if url_str.startswith("http://") or url_str.startswith("https://") else 0
    features["special_char_count"] = sum(1 for c in url_str if c in "@-_.,;:#~!$&'()*+/:=?")
    features["entropy"] = compute_entropy(url_str)

    path = parsed.path
    features["path_depth"] = len([p for p in path.split("/") if p]) if path else 0
    features["domain_length"] = len(parsed.hostname or "")
    features["is_domain_ip"] = 1 if parsed.hostname and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", parsed.hostname) else 0
    features["has_at_symbol"] = 1 if "@" in url_str else 0
    features["has_double_slash_redirect"] = 1 if url_str.count("//") > 1 else 0

    try:
        tld_part = get_tld(url_str, fail_silently=True)
        features["tld_length"] = len(tld_part) if tld_part else 0
    except Exception:
        features["tld_length"] = 0

    features["query_param_count"] = len(parsed.query.split("&")) if parsed.query else 0
    features["path_length"] = len(path) if path else 0

    return features


def compute_entropy(s):
    if not s:
        return 0
    prob = [s.count(c) / len(s) for c in set(s)]
    return -sum(p * math.log2(p) for p in prob)


def extract_url_features(urls, label, source):
    rows = []
    for url in urls:
        try:
            feats = extract_features(url)
            feats["url"] = url
            feats["label"] = label
            feats["source"] = source
            rows.append(feats)
        except Exception:
            continue
    return rows


def main():
    print("=" * 60)
    print("PhishTrap Dataset Builder")
    print("=" * 60)

    print("\n[1/5] Downloading Phishing.Database domains...")
    pd_domains = download_phishing_database()
    print(f"  Got {len(pd_domains):,} domains")

    print("\n[2/5] Downloading OpenPhish feed...")
    op_urls = download_openphish()
    print(f"  Got {len(op_urls):,} URLs")

    op_domains = set()
    for url in op_urls:
        domain = extract_domain_from_url(url)
        if domain:
            op_domains.add(domain)
    print(f"  Extracted {len(op_domains):,} unique domains from OpenPhish")

    phishing_domains = pd_domains | op_domains
    print(f"\n  Total unique phishing domains: {len(phishing_domains):,}")

    print("\n[3/5] Downloading Tranco top 10K legitimate domains...")
    legit_domains = download_tranco(limit=10000)
    legit_domains = legit_domains - phishing_domains
    print(f"  Got {len(legit_domains):,} legitimate domains (after filtering out phishing)")

    target = min(len(phishing_domains), len(legit_domains), 10000)
    print(f"\n[4/5] Sampling {target:,} per class and extracting features...")

    phishing_sample = random.sample(sorted(phishing_domains), min(target, len(phishing_domains)))
    legit_sample = random.sample(sorted(legit_domains), min(target, len(legit_domains)))

    print("  Extracting phishing features...")
    phishing_rows = extract_url_features(phishing_sample, label=1, source="phishing_database+openphish")
    print(f"  Got {len(phishing_rows):,} phishing rows")

    print("  Extracting legitimate features...")
    legit_rows = extract_url_features(legit_sample, label=0, source="tranco")
    print(f"  Got {len(legit_rows):,} legitimate rows")

    df = pd.DataFrame(phishing_rows + legit_rows)
    df = df.sample(frac=1, random_state=SEED).reset_index(drop=True)
    print(f"\n  Total dataset: {len(df):,} rows, {len(df.columns)} columns")
    print(f"  Label distribution: {df['label'].value_counts().to_dict()}")

    print("\n[5/5] Saving and uploading to Hugging Face...")
    csv_path = OUTPUT_DIR / "phishtrap_full.csv"
    df.to_csv(csv_path, index=False)
    print(f"  Saved to {csv_path}")

    train = df.sample(frac=0.7, random_state=SEED)
    remaining = df.drop(train.index)
    val = remaining.sample(frac=0.5, random_state=SEED)
    test = remaining.drop(val.index)

    splits = {"train": train, "val": val, "test": test}
    for name, split_df in splits.items():
        split_df.to_csv(OUTPUT_DIR / f"{name}.csv", index=False)
        split_df.to_parquet(OUTPUT_DIR / f"{name}.parquet", index=False)
        print(f"  {name}: {len(split_df):,} rows")

    df.to_parquet(OUTPUT_DIR / "phishtrap_full.parquet", index=False)

    print("\n  Uploading to Hugging Face...")
    api = HfApi(token=HF_TOKEN)

    repo_id = f"{HF_USER}/{DATASET_NAME}"
    try:
        api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
        print(f"  Repo {repo_id} ready")
    except Exception as e:
        print(f"  Repo may already exist: {e}")

    upload_folder(
        folder_path=str(OUTPUT_DIR),
        repo_id=repo_id,
        repo_type="dataset",
        token=HF_TOKEN,
        path_in_repo="data",
    )
    print(f"  Uploaded data/ folder to {repo_id}")

    print("\n" + "=" * 60)
    print("PhishTrap dataset build complete!")
    print(f"  Dataset: {repo_id}")
    print(f"  Total samples: {len(df):,}")
    print(f"  Features: {len(df.columns) - 3}")  # minus url, label, source
    print("=" * 60)


if __name__ == "__main__":
    main()
