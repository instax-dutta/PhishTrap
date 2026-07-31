import math

import pytest

from phishtrap_pipeline.features import (
    extract_features,
    compute_entropy,
    extract_domain_from_url,
    extract_url_features,
)
from phishtrap_pipeline.config import FEATURE_COLUMNS


class TestComputeEntropy:
    def test_empty_string(self):
        assert compute_entropy("") == 0.0

    def test_uniform_distribution(self):
        e = compute_entropy("ab")
        assert e == 1.0

    def test_skewed_distribution(self):
        e = compute_entropy("aaaab")
        assert 0.5 < e < 1.0


class TestExtractDomainFromUrl:
    def test_http_url(self):
        assert extract_domain_from_url("http://evil.com/login") == "evil.com"

    def test_domain_only(self):
        assert extract_domain_from_url("evil.com") == "evil.com"

    def test_with_www(self):
        assert extract_domain_from_url("https://www.google.com/search") == "www.google.com"


class TestExtractFeatures:
    def test_normal_url(self):
        feats = extract_features("https://google.com/search")
        assert feats["protocol_exists"] == 1
        assert feats["trusted_tld"] == 1
        assert feats["has_at_symbol"] == 0
        assert feats["is_domain_ip"] == 0

    def test_phishy_url(self):
        feats = extract_features("http://login-verify-paypal.secure-login.evil.com/@phishing")
        assert feats["hyphen_count"] > 0
        assert feats["has_at_symbol"] == 1
        assert feats["subdomain_count"] >= 2

    def test_ip_url(self):
        feats = extract_features("http://192.168.1.1/login")
        assert feats["is_domain_ip"] == 1

    def test_all_feature_columns_present(self):
        feats = extract_features("https://example.com")
        for col in FEATURE_COLUMNS:
            assert col in feats, f"Missing feature: {col}"

    def test_no_nan_or_inf_values(self):
        feats = extract_features("https://example.com/path?q=1&r=2")
        for k, v in feats.items():
            if isinstance(v, float):
                assert not math.isnan(v), f"NaN in {k}"
                assert not math.isinf(v), f"Inf in {k}"

    def test_tld_length(self):
        feats = extract_features("https://example.co.uk/path")
        assert feats["tld_length"] > 0


class TestExtractUrlFeatures:
    def test_extracts_multiple_urls(self):
        urls = {"http://evil.com", "http://good.com"}
        rows = extract_url_features(urls, 1, "test")
        assert len(rows) == 2
        for row in rows:
            assert row["label"] == 1
            assert row["source"] == "test"
            for col in FEATURE_COLUMNS:
                assert col in row
