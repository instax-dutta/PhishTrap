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

    def test_returns_new_when_no_existing(self):
        new_row = {
            "url": "http://b.com", "url_length": 10, "label": 0, "source": "new",
            **{col: 0 for col in FEATURE_COLUMNS[1:]},
        }
        merged = merge_with_existing([new_row], None)
        assert len(merged) == 1


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
