import time
import logging

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "PhishTrap-Pipeline/2.0"

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


def fetch_url(url, retries=MAX_RETRIES):
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(
                url, timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_exc = e
            logger.warning(
                "Fetch failed (attempt %d/%d) for %s: %s",
                attempt + 1, retries, url, e,
            )
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    logger.error("All %d retries exhausted for %s: %s", retries, url, last_exc)
    raise last_exc


def fetch_phishing_database():
    text = fetch_url("https://phish.co.za/latest/ALL-phishing-domains.lst")
    domains = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line and not line.startswith("#"):
            domains.add(line)
    return domains


def fetch_openphish():
    text = fetch_url("https://openphish.com/feed.txt")
    urls = set()
    for line in text.strip().splitlines():
        line = line.strip().lower()
        if line:
            urls.add(line)
    return urls


def fetch_phishstats(max_pages=4):
    urls = set()
    base = "https://api.phishstats.info/api/phishing"
    for page in range(1, max_pages + 1):
        try:
            text = fetch_url(f"{base}?_sort=-id&_p={page}&_size=100", retries=2)
            records = _parse_phishstats_json(text)
            if not records:
                break
            for record in records:
                url = (record.get("url") or "").strip().lower()
                if url:
                    urls.add(url)
        except Exception as e:
            logger.warning("PhishStats page %d failed: %s", page, e)
            break
    return urls


def _parse_phishstats_json(text):
    import json
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return data


def fetch_tranco(limit=10000):
    text = fetch_url("https://tranco-list.eu/download/Y8VQG/10000")
    domains = set()
    for line in text.strip().splitlines():
        parts = line.strip().split(",")
        domain = parts[1].strip().lower() if len(parts) >= 2 else parts[0].strip().lower()
        domains.add(domain)
        if len(domains) >= limit:
            break
    return domains


def fetch_all_sources():
    results = {}
    sources = [
        ("phishing_database", fetch_phishing_database),
        ("openphish", fetch_openphish),
        ("phishstats", fetch_phishstats),
        ("tranco", fetch_tranco),
    ]
    for name, fn in sources:
        try:
            data = fn()
            results[name] = data
            logger.info("Fetched %d items from %s", len(data), name)
        except Exception as e:
            logger.error("Failed to fetch %s: %s", name, e)
            results[name] = set()
    return results
