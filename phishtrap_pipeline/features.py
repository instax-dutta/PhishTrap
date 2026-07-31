import math
import re
from urllib.parse import urlparse

from tld import get_tld

from phishtrap_pipeline.config import TRUSTED_TLDS


def compute_entropy(s):
    if not s:
        return 0.0
    prob = [s.count(c) / len(s) for c in set(s)]
    return -sum(p * math.log2(p) for p in prob)


def extract_domain_from_url(url):
    try:
        if url.startswith("http"):
            parsed = urlparse(url)
            return parsed.netloc.lower()
        return url.lower().strip()
    except Exception:
        return url.lower().strip()


def extract_features(url):
    url_str = str(url).lower().strip()
    if not url_str.startswith("http"):
        url_str = "http://" + url_str
    parsed = urlparse(url_str)

    hostname = parsed.hostname or ""
    path = parsed.path or ""

    features = {}
    features["url_length"] = len(url_str)
    features["hyphen_count"] = url_str.count("-")
    features["digit_count"] = sum(1 for c in url_str if c.isdigit())
    features["subdomain_count"] = max(0, len(hostname.split(".")) - 2)

    try:
        tld_info = get_tld(url_str, fail_silently=True)
        features["trusted_tld"] = 1 if tld_info and f".{tld_info}" in TRUSTED_TLDS else 0
    except Exception:
        features["trusted_tld"] = 0

    features["protocol_exists"] = 1 if re.match(r"^https?://", str(url).lower().strip()) else 0
    features["special_char_count"] = sum(1 for c in url_str if c in "@-_.,;:#~!$&'()*+/:=?")
    features["entropy"] = compute_entropy(url_str)
    features["path_depth"] = len([p for p in path.split("/") if p])
    features["domain_length"] = len(hostname)
    features["is_domain_ip"] = 1 if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", hostname) else 0
    features["has_at_symbol"] = 1 if "@" in url_str else 0
    features["has_double_slash_redirect"] = 1 if url_str.count("//") > 1 else 0

    try:
        tld_part = get_tld(url_str, fail_silently=True)
        features["tld_length"] = len(tld_part) if tld_part else 0
    except Exception:
        features["tld_length"] = 0

    features["query_param_count"] = len(parsed.query.split("&")) if parsed.query else 0
    features["path_length"] = len(path)
    return features


def extract_url_features(urls, label, source_tag):
    rows = []
    for url in urls:
        try:
            feats = extract_features(url)
            feats["url"] = url
            feats["label"] = label
            feats["source"] = source_tag
            rows.append(feats)
        except Exception:
            continue
    return rows
