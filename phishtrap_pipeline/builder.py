import logging
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
    logger.info(
        "Rebalancing to %d per class (phishing=%d, legit=%d)",
        n, len(phishing), len(legit),
    )

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
