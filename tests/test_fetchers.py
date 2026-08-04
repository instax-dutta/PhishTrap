import pytest
import responses

from phishtrap_pipeline import fetchers


@responses.activate
def test_fetch_url_success():
    responses.add(
        responses.GET, "http://example.com/feed.txt",
        body="a.com\nb.com\n", status=200,
    )
    text = fetchers.fetch_url("http://example.com/feed.txt", retries=1)
    assert "a.com" in text


@responses.activate
def test_fetch_url_retries_on_failure():
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(
        responses.GET, "http://example.com/feed.txt",
        body="ok\n", status=200,
    )
    text = fetchers.fetch_url("http://example.com/feed.txt", retries=3)
    assert text == "ok\n"


@responses.activate
def test_fetch_url_exhausts_retries():
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    responses.add(responses.GET, "http://example.com/feed.txt", status=500)
    with pytest.raises(Exception):
        fetchers.fetch_url("http://example.com/feed.txt", retries=3)


@responses.activate
def test_fetch_openphish():
    responses.add(
        responses.GET, "https://openphish.com/feed.txt",
        body="http://evil.com/login\nhttp://bad.com\n", status=200,
    )
    urls = fetchers.fetch_openphish()
    assert "http://evil.com/login" in urls
    assert "http://bad.com" in urls
    assert len(urls) == 2


@responses.activate
def test_fetch_tranco():
    csv_data = "1,google.com\n2,facebook.com\n3,youtube.com\n"
    responses.add(
        responses.GET, "https://tranco-list.eu/download/Y8VQG/10000",
        body=csv_data, status=200,
    )
    domains = fetchers.fetch_tranco(limit=3)
    assert domains == {"google.com", "facebook.com", "youtube.com"}


@responses.activate
def test_fetch_phishstats_json():
    payload = '{"error": "boom"}'
    responses.add(
        responses.GET, "https://api.phishstats.info/api/phishing?_sort=-id&_p=1&_size=100",
        body=payload, status=200,
    )
    urls = fetchers.fetch_phishstats(max_pages=1)
    assert urls == set()


@responses.activate
def test_fetch_phishstats_parses_records():
    payload = '[{"id":1,"url":"http://evil1.com/x"},{"id":2,"url":"http://evil2.com/y"},{"id":3,"url":null}]'
    responses.add(
        responses.GET, "https://api.phishstats.info/api/phishing?_sort=-id&_p=1&_size=100",
        body=payload, status=200,
    )
    urls = fetchers.fetch_phishstats(max_pages=1)
    assert urls == {"http://evil1.com/x", "http://evil2.com/y"}


@responses.activate
def test_fetch_phishstats_stops_on_empty_page():
    payload = "[]"
    responses.add(
        responses.GET, "https://api.phishstats.info/api/phishing?_sort=-id&_p=1&_size=100",
        body=payload, status=200,
    )
    responses.add(
        responses.GET, "https://api.phishstats.info/api/phishing?_sort=-id&_p=2&_size=100",
        body=payload, status=200,
    )
    urls = fetchers.fetch_phishstats(max_pages=2)
    assert urls == set()


@responses.activate
def test_fetch_url_uses_fallback_mirror():
    responses.add(
        responses.GET, "https://primary.example/feed.txt",
        body="500\n" * 3, status=500,
    )
    responses.add(
        responses.GET, "https://mirror.example/feed.txt",
        body="evil.com\n", status=200,
    )
    text = fetchers.fetch_url(
        "https://primary.example/feed.txt",
        retries=2,
        fallbacks=["https://mirror.example/feed.txt"],
    )
    assert "evil.com" in text


@responses.activate
def test_fetch_url_falls_back_to_github_mirror_for_phish_database():
    responses.add(
        responses.GET,
        "https://phish.co.za/latest/ALL-phishing-domains.lst",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-domains-ACTIVE.txt",
        body="evil1.com\nevil2.com\n", status=200,
    )
    domains = fetchers.fetch_phishing_database()
    assert domains == {"evil1.com", "evil2.com"}


@responses.activate
def test_fetch_openphish_falls_back_to_github_mirror():
    responses.add(
        responses.GET, "https://openphish.com/feed.txt",
        status=503,
    )
    responses.add(
        responses.GET,
        "https://raw.githubusercontent.com/openphish/public_feed/master/feed.txt",
        body="http://evil.com/login\n", status=200,
    )
    urls = fetchers.fetch_openphish()
    assert urls == {"http://evil.com/login"}


@responses.activate
def test_fetch_all_sources_partial_failure():
    responses.add(
        responses.GET, "https://phish.co.za/latest/ALL-phishing-domains.lst",
        body="evil.com\n", status=200,
    )
    responses.add(responses.GET, "https://openphish.com/feed.txt", status=500)
    responses.add(
        responses.GET, "https://api.phishstats.info/api/phishing?_sort=-id&_p=1&_size=100",
        status=500,
    )
    responses.add(
        responses.GET, "https://tranco-list.eu/download/Y8VQG/10000",
        body="1,good.com\n", status=200,
    )
    results = fetchers.fetch_all_sources()
    assert "evil.com" in results["phishing_database"]
    assert results["openphish"] == set()
    assert results["phishstats"] == set()
    assert "good.com" in results["tranco"]
