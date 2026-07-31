import os
from pathlib import Path

SEED = 42
HF_USER = "saidutta69"
DATASET_NAME = "PhishTrap"
REPO_ID = f"{HF_USER}/{DATASET_NAME}"

OUTPUT_DIR = Path("/tmp/phishtrap")

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
