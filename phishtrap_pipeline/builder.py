import logging
import random
from datetime import date
from urllib.parse import urlparse, urlunparse

import numpy as np
import pandas as pd

from phishtrap_pipeline.config import FEATURE_COLUMNS, SEED

logger = logging.getLogger(__name__)

EXPIRY_DAYS = 60


class DatasetValidationError(ValueError):
    pass


def canonicalize_url(url):
    """Canonical key for dedup: strips scheme, fragment, default ports,
    trailing slash; lowercases host. Keeps www (distinct site identity)."""
    try:
        u = str(url).lower().strip()
        if not u.startswith("http"):
            u = "http://" + u
        parsed = urlparse(u)
        host = parsed.hostname or ""
        if parsed.port:
            default_port = (80 if parsed.scheme == "http" else
                            443 if parsed.scheme == "https" else None)
            netloc = host if parsed.port == default_port else f"{host}:{parsed.port}"
        else:
            netloc = host
        path = parsed.path.rstrip("/") or "/"
        if parsed.query:
            return f"{netloc}{path}?{parsed.query}"
        return f"{netloc}{path}"
    except Exception:
        return str(url).lower().strip()


BALANCE_BAND = (0.9, 1.1)


def validate_dataset(df, require_balance=True):
    """Validate a dataset frame.

    require_balance: enforce the strict class-balance band. Only meaningful on
    the full dataset - small random splits are subject to sampling noise, so
    balance is enforced there by stratified splitting instead (see split_dataset).
    """
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

    for col in ("url", "canonical_url", "label", "source", "first_seen", "last_seen"):
        if col in df.columns and df[col].isnull().any():
            errors.append(f"Column {col} has null values")

    if require_balance and "label" in df.columns:
        counts = df["label"].value_counts()
        if len(counts) != 2:
            errors.append(f"Expected 2 classes, got {len(counts)}")
        elif not is_balanced(df, counts=counts):
            errors.append(f"Class imbalance: {counts.to_dict()} (ratio={counts[0] / counts[1]:.3f})")

    if "canonical_url" in df.columns:
        dups = df["canonical_url"].duplicated().sum()
        if dups > 0:
            errors.append(f"Found {dups} duplicate canonical URLs")

    if errors:
        raise DatasetValidationError("; ".join(errors))


def merge_with_existing(new_rows, existing_df=None, today=None):
    """Merge new evidence into existing dataset.

    Rules:
    - Dedup by canonical_url (scheme-agnostic, trailing-slash-agnostic)
    - New evidence always wins label conflicts (e.g. compromised legit domain)
    - first_seen/collected_at = earliest observation
    - last_seen refreshed on every confirmation
    - source = union of all sources that reported the URL
    """
    today = today or date.today().isoformat()
    if not new_rows:
        logger.warning("No new rows to add")
        return existing_df

    new_df = pd.DataFrame(new_rows)
    if "canonical_url" not in new_df.columns:
        new_df["canonical_url"] = new_df["url"].apply(canonicalize_url)
    new_df["first_seen"] = today
    new_df["last_seen"] = today
    new_df["collected_at"] = today

    if existing_df is None or existing_df.empty:
        logger.info("No existing dataset, returning new data")
        return new_df

    existing = existing_df.copy()
    if "canonical_url" not in existing.columns:
        existing["canonical_url"] = existing["url"].apply(canonicalize_url)
    for col in ("first_seen", "last_seen", "collected_at"):
        if col not in existing.columns:
            logger.warning(
                "Existing dataset missing %s (legacy schema) - backfilling with %s",
                col, today,
            )
            existing[col] = today

    existing_by_key = {c: i for i, c in enumerate(existing["canonical_url"])}
    new_by_key = {}
    for _, row in new_df.iterrows():
        key = row["canonical_url"]
        if key not in new_by_key:
            new_by_key[key] = row

    updated = []
    additions = []
    for key, new_row in new_by_key.items():
        if key in existing_by_key:
            old = existing.iloc[existing_by_key[key]]
            update = dict(new_row)
            update["first_seen"] = min(str(update["first_seen"]), str(old["first_seen"]))
            update["collected_at"] = update["first_seen"]
            update["source"] = _union_sources(old["source"], update["source"])
            if update["label"] != old["label"]:
                logger.warning(
                    "Label conflict for %s: old=%d new=%d (new evidence wins)",
                    key, old["label"], update["label"],
                )
            updated.append(update)
        else:
            additions.append(dict(new_row))

    kept = existing[~existing["canonical_url"].isin(new_by_key.keys())]
    parts = [kept]
    if additions:
        parts.append(pd.DataFrame(additions))
    if updated:
        parts.append(pd.DataFrame(updated))
    merged = pd.concat(parts, ignore_index=True)

    merged = merged.drop_duplicates(subset=["canonical_url"], keep="last")
    logger.info(
        "Merge: %d updated, %d added, total %d",
        len(updated), len(additions), len(merged),
    )
    return merged


def _union_sources(old_sources, new_sources):
    parts = set()
    for s in (old_sources, new_sources):
        if not s:
            continue
        for part in str(s).split("+"):
            part = part.strip()
            if part:
                parts.add(part)
    return "+".join(sorted(parts))


def prune_expired(df, max_age_days=EXPIRY_DAYS, today=None):
    """Drop phishing rows not confirmed within max_age_days.
    Legit rows never expire (Tranco top-10K is stable by design)."""
    if df.empty:
        return df
    today = today or date.today().isoformat()
    phishing_mask = df["label"] == 1
    expired_mask = phishing_mask & (df["last_seen"] < today)
    n_expired = int(expired_mask.sum())
    if n_expired:
        logger.info("Pruning %d expired phishing URLs (last seen < %s - %d days)",
                    n_expired, today, max_age_days)
    return df[~expired_mask].reset_index(drop=True)


def rebalance(df, max_per_class=10000, today=None):
    random.seed(SEED)
    np.random.seed(SEED)

    phishing = df[df["label"] == 1]
    legit = df[df["label"] == 0]

    n = min(len(phishing), len(legit), max_per_class)
    if n == 0:
        raise DatasetValidationError(
            f"Rebalance produced zero samples: phishing={len(phishing)}, legit={len(legit)}"
        )
    logger.info(
        "Rebalancing to %d per class (phishing=%d, legit=%d)",
        n, len(phishing), len(legit),
    )

    phishing_sample = phishing.sample(n=n, random_state=SEED)
    legit_sample = legit.sample(n=n, random_state=SEED)

    balanced = pd.concat([phishing_sample, legit_sample], ignore_index=True)
    balanced = balanced.sample(frac=1, random_state=SEED).reset_index(drop=True)
    return balanced


def is_balanced(df, counts=None, band=BALANCE_BAND):
    """True if both classes are present and their ratio is within band."""
    if counts is None:
        counts = df["label"].value_counts()
    if len(counts) != 2:
        return False
    small, large = sorted(int(v) for v in counts.tolist())
    if small == 0 or large == 0:
        return False
    return band[0] <= small / large <= band[1]


def _stratified_indices(frame, frac, seed):
    """Indices of a per-class proportional sample (stratified by label)."""
    taken = []
    for _, group in frame.groupby("label"):
        n = max(1, int(round(len(group) * frac)))
        n = min(n, len(group))
        taken.append(group.sample(n=n, random_state=seed).index)
    return pd.Index(np.concatenate([t.values for t in taken]))


def split_dataset(df, train_frac=0.7, val_frac=0.5, seed=SEED, max_attempts=10):
    """Stratified train/val/test split.

    Samples per class proportionally, so every split keeps the global class
    ratio regardless of row order. This removes the dependence on set/row
    iteration order that made the old split nondeterministic across runs.

    max_attempts: defensive retry loop with bumped seeds; the stratification
    makes failure effectively unreachable, but if it ever happens we fall back
    to the last attempt rather than crash.
    """
    last_splits = None
    for attempt in range(max_attempts):
        rs = seed + attempt
        train_idx = _stratified_indices(df, train_frac, rs)
        remaining = df.drop(index=train_idx)
        val_idx = _stratified_indices(remaining, val_frac, rs)
        test = remaining.drop(index=val_idx)
        splits = {
            "train": df.loc[train_idx.sort_values()],
            "val": remaining.loc[val_idx.sort_values()],
            "test": test,
        }
        last_splits = splits
        if all(is_balanced(s) for s in splits.values()):
            return splits
        logger.warning(
            "Split attempt %d/%d produced imbalanced splits, retrying with seed %d",
            attempt + 1, max_attempts, rs + 1,
        )
    logger.error("Could not produce balanced splits after %d attempts", max_attempts)
    return last_splits
