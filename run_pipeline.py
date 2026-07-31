#!/usr/bin/env python3
"""
PhishTrap auto-update pipeline entry point.
Called by GitHub Actions cron workflow.
"""
import json
import logging
import sys
from datetime import date, datetime, timezone

from phishtrap_pipeline.config import OUTPUT_DIR, get_hf_token
from phishtrap_pipeline.fetchers import fetch_all_sources
from phishtrap_pipeline.features import extract_url_features, extract_domain_from_url
from phishtrap_pipeline.builder import (
    merge_with_existing,
    prune_expired,
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
    import pandas as pd

    token = get_hf_token()
    api = HfApi(token=token)
    try:
        files = api.list_repo_files(repo_id=REPO_ID, repo_type="dataset")
        if "data/phishtrap_full.csv" in files:
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
    today = date.today().isoformat()
    logger.info(
        "Starting PhishTrap pipeline (force_full=%s, max_samples=%d, dry_run=%s)",
        args.force_full, args.max_samples, args.dry_run,
    )

    logger.info("Step 1: Fetching data from sources...")
    source_data = fetch_all_sources()

    phishing_rows = []
    for key in ("phishing_database", "openphish", "phishstats"):
        items = source_data.get(key, set())
        urls = {i if i.startswith("http") else f"http://{i}" for i in items}
        if urls:
            rows = extract_url_features(urls, label=1, source_tag=key)
            logger.info("  %s: %d rows", key, len(rows))
            phishing_rows.extend(rows)
    logger.info("Total phishing rows: %d", len(phishing_rows))

    legit_domains = source_data.get("tranco", set())
    legit_domains = legit_domains - {extract_domain_from_url(r["url"]) for r in phishing_rows}
    legit_urls = {f"http://{d}" for d in legit_domains}
    legit_rows = extract_url_features(legit_urls, label=0, source_tag="tranco")
    logger.info("Total legit rows: %d", len(legit_rows))

    if not phishing_rows or not legit_rows:
        logger.error("No data extracted from sources, aborting")
        sys.exit(1)

    logger.info("Step 2: Merging with existing dataset...")
    existing = None if args.force_full else download_existing_dataset()

    all_new = phishing_rows + legit_rows
    merged = merge_with_existing(all_new, existing, today=today)

    if merged is None or merged.empty:
        logger.error("Merge produced empty dataset, aborting")
        sys.exit(1)

    logger.info("Step 3: Pruning expired phishing URLs...")
    merged = prune_expired(merged, today=today)
    logger.info("After pruning: %d rows", len(merged))

    logger.info("Step 4: Rebalancing...")
    balanced = rebalance(merged, max_per_class=args.max_samples)
    validate_dataset(balanced)
    logger.info("Balanced dataset: %d rows", len(balanced))

    logger.info("Step 5: Splitting...")
    splits = split_dataset(balanced)
    for name, split_df in splits.items():
        logger.info("  %s: %d rows", name, len(split_df))

    metadata = {
        "build_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "build_date": today,
        "rows": int(len(balanced)),
        "features": 16,
        "feature_columns": list(balanced[["url_length", "hyphen_count", "digit_count",
                                         "subdomain_count", "trusted_tld", "protocol_exists",
                                         "special_char_count", "entropy", "path_depth",
                                         "domain_length", "is_domain_ip", "has_at_symbol",
                                         "has_double_slash_redirect", "tld_length",
                                         "query_param_count", "path_length"]].columns),
        "class_distribution": balanced["label"].value_counts().to_dict(),
        "source_distribution": balanced["source"].value_counts().to_dict(),
        "label_balance_ratio": float(
            balanced["label"].value_counts().iloc[1] / balanced["label"].value_counts().iloc[0]
        ),
        "expiry_days": 60,
        "schema_version": 2,
    }
    logger.info("Metadata: %s", json.dumps({k: v for k, v in metadata.items() if k != "feature_columns"}))

    if args.dry_run:
        logger.info("DRY RUN: skipping upload. Dataset size would be %d rows.", len(balanced))
        import os
        out = os.environ.get("PHISTRAP_OUT_DIR", "/tmp/phishtrap/dry_run")
        os.makedirs(out, exist_ok=True)
        balanced.to_csv(f"{out}/phishtrap_full.csv", index=False)
        logger.info("Dry-run dataset written to %s/phishtrap_full.csv", out)
        return

    logger.info("Step 6: Uploading to Hugging Face...")
    repo_url = upload_dataset(splits, OUTPUT_DIR / "data", metadata=metadata)
    logger.info("Uploaded to %s", repo_url)

    logger.info("Step 7: Verifying upload...")
    if verify_upload():
        logger.info("Pipeline completed successfully!")
    else:
        logger.error("Post-upload verification FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
