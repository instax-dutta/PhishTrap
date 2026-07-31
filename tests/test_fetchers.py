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
def test_fetch_all_sources_partial_failure():
    responses.add(
        responses.GET, "https://phish.co.za/latest/ALL-phishing-domains.lst",
        body="evil.com\n", status=200,
    )
    responses.add(responses.GET, "https://openphish.com/feed.txt", status=500)
    responses.add(responses.GET, "https://phishstats.info/phish.csv", status=500)
    responses.add(
        responses.GET, "https://tranco-list.eu/download/Y8VQG/10000",
        body="1,good.com\n", status=200,
    )
    results = fetchers.fetch_all_sources()
    assert "evil.com" in results["phishing_database"]
    assert results["openphish"] == set()
    assert results["phishstats"] == set()
    assert "good.com" in results["tranco"]
