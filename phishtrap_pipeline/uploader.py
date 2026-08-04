import json
import logging
import random
import shutil
import time
from pathlib import Path

import pandas as pd
from huggingface_hub import HfApi, upload_folder

from phishtrap_pipeline.config import REPO_ID, get_hf_token
from phishtrap_pipeline.builder import validate_dataset

logger = logging.getLogger(__name__)

UPLOAD_RETRIES = 5
VERIFY_RETRIES = 5


def _save_splits(splits, output_dir, metadata=None):
    output_dir = Path(output_dir)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, split_df in splits.items():
        validate_dataset(split_df, require_balance=False)
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

    if metadata:
        with open(output_dir / "dataset_info.json", "w") as f:
            json.dump(metadata, f, indent=2)
        logger.info("Saved dataset_info.json")


def upload_dataset(splits, output_dir, metadata=None, max_retries=UPLOAD_RETRIES):
    token = get_hf_token()
    api = HfApi(token=token)

    _save_splits(splits, output_dir, metadata=metadata)

    logger.info("Ensuring repo %s exists...", REPO_ID)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)

    last_exc = None
    for attempt in range(max_retries):
        try:
            logger.info(
                "Uploading data/ folder to %s (attempt %d/%d)...",
                REPO_ID, attempt + 1, max_retries,
            )
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
        except Exception as e:
            last_exc = e
            logger.error("Upload attempt %d/%d failed: %s", attempt + 1, max_retries, e)
            if attempt < max_retries - 1:
                time.sleep(min(2 ** attempt + random.uniform(0, 0.5), 60))
    raise last_exc


def verify_upload(repo_id=None):
    """Verify the published dataset, retrying to ride out HF propagation lag."""
    token = get_hf_token()
    api = HfApi(token=token)
    repo_id = repo_id or REPO_ID

    required = [
        "data/train.csv", "data/val.csv", "data/test.csv",
        "data/train.parquet", "data/val.parquet", "data/test.parquet",
        "data/phishtrap_full.csv", "data/phishtrap_full.parquet",
        "data/dataset_info.json",
    ]
    last_err = None
    for attempt in range(VERIFY_RETRIES):
        try:
            files = api.list_repo_files(repo_id=repo_id, repo_type="dataset")
            for f in required:
                if f not in files:
                    raise RuntimeError(f"missing {f}")

            train = api.hf_hub_download(repo_id=repo_id, repo_type="dataset", filename="data/train.csv")
            df = pd.read_csv(train)
            validate_dataset(df)
            logger.info("Verification passed: %d rows in train split", len(df))
            return True
        except Exception as e:
            last_err = e
            logger.error(
                "Verification attempt %d/%d failed: %s",
                attempt + 1, VERIFY_RETRIES, e,
            )
            if attempt < VERIFY_RETRIES - 1:
                time.sleep(min(2 ** attempt + random.uniform(0, 0.5), 20))
    logger.error("Verification failed after %d attempts: %s", VERIFY_RETRIES, last_err)
    return False
