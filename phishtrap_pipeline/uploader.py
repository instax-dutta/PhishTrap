import logging
import shutil
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi, upload_folder

from phishtrap_pipeline.config import REPO_ID, get_hf_token
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
