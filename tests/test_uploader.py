import pytest
import pandas as pd

from phishtrap_pipeline.uploader import _save_splits
from phishtrap_pipeline.config import FEATURE_COLUMNS


def _make_split_df(n=100, label=0, offset=0):
    half = n // 2
    labels = [label] * half + [1 - label] * (n - half)
    return pd.DataFrame({
        **{col: [0] * n for col in FEATURE_COLUMNS},
        "url": [f"http://example{offset + i}.com" for i in range(n)],
        "label": labels,
        "source": ["test"] * n,
    })


def test_save_splits_creates_files(tmp_path):
    splits = {
        "train": _make_split_df(70, label=0, offset=0),
        "val": _make_split_df(16, label=0, offset=100),
        "test": _make_split_df(16, label=0, offset=200),
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
