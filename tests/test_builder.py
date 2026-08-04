import pytest
import pandas as pd
import numpy as np

from phishtrap_pipeline.builder import (
    validate_dataset,
    DatasetValidationError,
    canonicalize_url,
    merge_with_existing,
    prune_expired,
    rebalance,
    split_dataset,
)
from phishtrap_pipeline.config import FEATURE_COLUMNS


def _make_valid_df(n=100):
    rows = []
    for i in range(n):
        row = {col: 0 for col in FEATURE_COLUMNS}
        row["url"] = f"http://example{i}.com"
        row["canonical_url"] = canonicalize_url(row["url"])
        row["label"] = i % 2
        row["source"] = "test"
        row["first_seen"] = "2026-07-01"
        row["last_seen"] = "2026-07-01"
        row["collected_at"] = "2026-07-01"
        rows.append(row)
    return pd.DataFrame(rows)


class TestCanonicalizeUrl:
    def test_scheme_agnostic(self):
        assert canonicalize_url("http://evil.com/x") == canonicalize_url("https://evil.com/x")

    def test_trailing_slash_stripped(self):
        assert canonicalize_url("http://evil.com/x/") == canonicalize_url("http://evil.com/x")

    def test_case_insensitive_host(self):
        assert canonicalize_url("http://EVIL.com/X") == canonicalize_url("http://evil.com/x")

    def test_fragment_stripped(self):
        assert canonicalize_url("http://evil.com/x#frag") == canonicalize_url("http://evil.com/x")

    def test_default_port_stripped(self):
        assert canonicalize_url("http://evil.com:80/x") == canonicalize_url("http://evil.com/x")

    def test_www_preserved(self):
        assert canonicalize_url("http://www.google.com") != canonicalize_url("http://google.com")

    def test_plain_domain(self):
        assert canonicalize_url("evil.com") == "evil.com/"


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

    def test_imbalanced_classes_passes_when_require_balance_false(self):
        df = _make_valid_df()
        df["label"] = 0
        df.iloc[0, df.columns.get_loc("label")] = 1
        validate_dataset(df, require_balance=False)

    def test_duplicate_canonical_urls_raises(self):
        df = _make_valid_df()
        df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)

    def test_null_canonical_url_raises(self):
        df = _make_valid_df()
        df.loc[0, "canonical_url"] = np.nan
        with pytest.raises(DatasetValidationError):
            validate_dataset(df)


class TestMergeWithExisting:
    def test_merges_new_urls(self):
        existing = _make_valid_df(10)
        new_row = {
            **{col: 0 for col in FEATURE_COLUMNS},
            "url": "http://brand-new.com", "label": 0, "source": "tranco",
        }
        merged = merge_with_existing([new_row], existing, today="2026-07-31")
        assert len(merged) == 11
        row = merged[merged["url"] == "http://brand-new.com"].iloc[0]
        assert row["first_seen"] == "2026-07-31"
        assert row["last_seen"] == "2026-07-31"
        assert row["collected_at"] == "2026-07-31"

    def test_deduplicates_http_https_variants(self):
        existing = pd.DataFrame({
            **{col: [0] for col in FEATURE_COLUMNS},
            "url": ["http://a.com"], "label": [1], "source": ["openphish"],
            "first_seen": ["2026-07-01"], "last_seen": ["2026-07-01"],
            "collected_at": ["2026-07-01"],
        })
        existing["canonical_url"] = existing["url"].apply(canonicalize_url)
        dup_row = {
            **{col: 0 for col in FEATURE_COLUMNS},
            "url": "https://a.com/", "label": 1, "source": "openphish",
        }
        merged = merge_with_existing([dup_row], existing, today="2026-07-31")
        assert len(merged) == 1

    def test_label_conflict_new_evidence_wins(self):
        existing = pd.DataFrame({
            **{col: [0] for col in FEATURE_COLUMNS},
            "url": ["http://compromised.com"], "label": [0], "source": ["tranco"],
            "first_seen": ["2026-01-01"], "last_seen": ["2026-07-01"],
            "collected_at": ["2026-01-01"],
        })
        existing["canonical_url"] = existing["url"].apply(canonicalize_url)
        new_evidence = {
            **{col: 1 for col in FEATURE_COLUMNS},
            "url": "http://compromised.com", "label": 1, "source": "openphish",
        }
        merged = merge_with_existing([new_evidence], existing, today="2026-07-31")
        assert len(merged) == 1
        row = merged.iloc[0]
        assert row["label"] == 1
        assert row["source"] == "openphish+tranco"
        assert row["first_seen"] == "2026-01-01"
        assert row["last_seen"] == "2026-07-31"

    def test_refreshes_last_seen_on_reconfirmation(self):
        existing = _make_valid_df(10)
        existing["first_seen"] = "2026-01-01"
        existing["last_seen"] = "2026-01-01"
        existing["collected_at"] = "2026-01-01"
        new_row = {
            **{col: 0 for col in FEATURE_COLUMNS},
            "url": "http://example0.com", "label": 0, "source": "tranco",
        }
        merged = merge_with_existing([new_row], existing, today="2026-07-31")
        row = merged[merged["url"] == "http://example0.com"].iloc[0]
        assert row["first_seen"] == "2026-01-01"
        assert row["last_seen"] == "2026-07-31"

    def test_returns_existing_when_no_new(self):
        existing = _make_valid_df(10)
        merged = merge_with_existing([], existing)
        assert len(merged) == 10

    def test_returns_new_when_no_existing(self):
        new_row = {
            **{col: 0 for col in FEATURE_COLUMNS},
            "url": "http://b.com", "label": 0, "source": "tranco",
        }
        merged = merge_with_existing([new_row], None, today="2026-07-31")
        assert len(merged) == 1
        assert merged.iloc[0]["first_seen"] == "2026-07-31"

    def test_source_union(self):
        existing = _make_valid_df(10)
        existing.loc[0, "source"] = "openphish"
        new_row = {
            **{col: 0 for col in FEATURE_COLUMNS},
            "url": "http://example0.com", "label": 0, "source": "phishing_database",
        }
        merged = merge_with_existing([new_row], existing, today="2026-07-31")
        row = merged[merged["url"] == "http://example0.com"].iloc[0]
        assert row["source"] == "openphish+phishing_database"


class TestPruneExpired:
    def test_prunes_old_phishing_only(self):
        df = _make_valid_df(100)
        df["label"] = 0
        df.iloc[0:20, df.columns.get_loc("label")] = 1
        df.loc[0:10, "last_seen"] = "2026-01-01"
        df.loc[11:19, "last_seen"] = "2026-07-31"
        df.loc[20:, "last_seen"] = "2026-07-31"
        pruned = prune_expired(df, today="2026-07-31")
        assert len(pruned) == len(df) - 11
        assert "2026-01-01" not in pruned["last_seen"].values

    def test_keeps_recent_phishing(self):
        df = _make_valid_df(100)
        df["label"] = 1
        df["last_seen"] = "2026-07-31"
        pruned = prune_expired(df, today="2026-07-31")
        assert len(pruned) == len(df)

    def test_legit_never_expires(self):
        df = _make_valid_df(10)
        df["label"] = 0
        df["last_seen"] = "2020-01-01"
        pruned = prune_expired(df, today="2026-07-31")
        assert len(pruned) == len(df)


class TestRebalance:
    def test_balanced_output(self):
        phishing = pd.DataFrame({
            **{col: [0] * 100 for col in FEATURE_COLUMNS},
            "url": [f"http://evil{i}.com" for i in range(100)],
            "canonical_url": [f"evil{i}.com" for i in range(100)],
            "label": [1] * 100,
            "source": ["test"] * 100,
            "first_seen": ["2026-07-01"] * 100,
            "last_seen": ["2026-07-01"] * 100,
            "collected_at": ["2026-07-01"] * 100,
        })
        legit = pd.DataFrame({
            **{col: [0] * 50 for col in FEATURE_COLUMNS},
            "url": [f"http://good{i}.com" for i in range(50)],
            "canonical_url": [f"good{i}.com" for i in range(50)],
            "label": [0] * 50,
            "source": ["test"] * 50,
            "first_seen": ["2026-07-01"] * 50,
            "last_seen": ["2026-07-01"] * 50,
            "collected_at": ["2026-07-01"] * 50,
        })
        df = pd.concat([phishing, legit], ignore_index=True)
        balanced = rebalance(df, max_per_class=50)
        assert balanced["label"].value_counts().to_dict() == {0: 50, 1: 50}

    def test_respects_max_per_class(self):
        phishing = pd.DataFrame({
            **{col: [0] * 200 for col in FEATURE_COLUMNS},
            "url": [f"http://evil{i}.com" for i in range(200)],
            "canonical_url": [f"evil{i}.com" for i in range(200)],
            "label": [1] * 200,
            "source": ["test"] * 200,
            "first_seen": ["2026-07-01"] * 200,
            "last_seen": ["2026-07-01"] * 200,
            "collected_at": ["2026-07-01"] * 200,
        })
        legit = pd.DataFrame({
            **{col: [0] * 200 for col in FEATURE_COLUMNS},
            "url": [f"http://good{i}.com" for i in range(200)],
            "canonical_url": [f"good{i}.com" for i in range(200)],
            "label": [0] * 200,
            "source": ["test"] * 200,
            "first_seen": ["2026-07-01"] * 200,
            "last_seen": ["2026-07-01"] * 200,
            "collected_at": ["2026-07-01"] * 200,
        })
        df = pd.concat([phishing, legit], ignore_index=True)
        balanced = rebalance(df, max_per_class=50)
        assert len(balanced) == 100
        assert balanced["label"].value_counts().to_dict() == {0: 50, 1: 50}

    def test_zero_samples_raises(self):
        df = _make_valid_df(10)
        df["label"] = 0
        with pytest.raises(DatasetValidationError):
            rebalance(df, max_per_class=50)


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
        train_urls = set(splits["train"]["canonical_url"])
        val_urls = set(splits["val"]["canonical_url"])
        test_urls = set(splits["test"]["canonical_url"])
        assert train_urls.isdisjoint(val_urls)
        assert train_urls.isdisjoint(test_urls)
        assert val_urls.isdisjoint(test_urls)

    def test_every_split_balanced_small_odd_sizes(self):
        df = _make_valid_df(957)
        df["label"] = [1] * 500 + [0] * 457
        splits = split_dataset(df)
        for name, split_df in splits.items():
            counts = split_df["label"].value_counts()
            assert len(counts) == 2
            ratio = min(counts) / max(counts)
            assert 0.9 <= ratio <= 1.1, (name, counts.to_dict())

    def test_balanced_regardless_of_row_order(self):
        df = _make_valid_df(1000)
        df["label"] = [1] * 500 + [0] * 500
        shuffled = df.sample(frac=1, random_state=123).reset_index(drop=True)
        a = split_dataset(df)
        b = split_dataset(shuffled)
        for name in ("train", "val", "test"):
            ca = a[name]["label"].value_counts().to_dict()
            cb = b[name]["label"].value_counts().to_dict()
            assert sorted(ca.values()) == sorted(cb.values()), (name, ca, cb)

    def test_does_not_raise_on_tiny_dataset(self):
        df = _make_valid_df(10)
        splits = split_dataset(df)
        assert len(splits["train"]) + len(splits["val"]) + len(splits["test"]) == 10
