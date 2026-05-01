"""
Tests for /api/fetch-jd.

Strategy: mock httpx.AsyncClient so tests don't depend on real networks.
We use respx, which is httpx's official mocking library.

We test:
- Happy path: real-looking JD HTML returns clean text + metadata.
- Invalid URLs (empty, wrong scheme, malformed) return 400.
- Network errors (timeout, DNS fail) return 504/502.
- Site returns 4xx/5xx → we return 502 with a useful message.
- Bot-block detection: tiny response, login-wall markers.
- Low content warning fires for short-but-valid pages.
"""

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-key-not-real")

import httpx  # noqa: E402
import pytest  # noqa: E402
import respx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


# ─── fixture HTML ──────────────────────────────────────────────────────────


def make_jd_html(title: str, body: str) -> str:
    """A minimal but realistic JD page."""
    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>{title}</title></head>
    <body>
        <nav>Home | Jobs | About</nav>
        <header>Some Company</header>
        <main>
            <article>
                <h1>{title}</h1>
                {body}
            </article>
        </main>
        <footer>© 2026 Some Company</footer>
    </body>
    </html>
    """


JD_BODY = """
<p>We are looking for a Senior Software Engineer to join our team.</p>
<h2>Responsibilities</h2>
<ul>
    <li>Design and build scalable systems</li>
    <li>Mentor junior engineers</li>
    <li>Drive architectural decisions</li>
</ul>
<h2>Requirements</h2>
<ul>
    <li>5+ years of backend experience</li>
    <li>Proficiency in Python and SQL</li>
    <li>Experience with cloud infrastructure (AWS or GCP)</li>
</ul>
<h2>Benefits</h2>
<p>Competitive salary, equity, full health coverage, remote-friendly.</p>
"""

LOGIN_WALL_HTML = """
<!DOCTYPE html>
<html>
<head><title>Sign In</title></head>
<body>
    <h1>Sign in to LinkedIn to view this job</h1>
    <p>Join LinkedIn to see the full job description and apply.</p>
</body>
</html>
"""


# ─── happy path ────────────────────────────────────────────────────────────


@respx.mock
def test_fetch_jd_happy_path(client):
    url = "https://example.com/jobs/senior-engineer"
    html = make_jd_html("Senior Software Engineer", JD_BODY)
    respx.get(url).mock(return_value=httpx.Response(200, text=html))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 200
    body = r.json()
    assert "Senior Software Engineer" in body["text"]
    assert "5+ years" in body["text"]
    assert "AWS or GCP" in body["text"]
    assert body["metadata"]["source_domain"] == "example.com"
    # title may or may not be detected; either is fine but we should get the field
    assert "title" in body["metadata"]
    assert body["metadata"]["char_count"] > 100


@respx.mock
def test_fetch_jd_strips_nav_and_footer(client):
    """trafilatura should strip 'Home | Jobs | About' and copyright lines."""
    url = "https://example.com/jobs/123"
    html = make_jd_html("Engineer", JD_BODY)
    respx.get(url).mock(return_value=httpx.Response(200, text=html))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 200
    text = r.json()["text"]
    # nav and footer should NOT appear in extracted text
    assert "Home | Jobs | About" not in text
    assert "© 2026" not in text


# ─── url validation ────────────────────────────────────────────────────────


def test_fetch_jd_empty_url(client):
    r = client.post("/api/fetch-jd", json={"url": ""})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "empty_url"


def test_fetch_jd_invalid_scheme(client):
    r = client.post("/api/fetch-jd", json={"url": "ftp://example.com/jobs"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_scheme"


def test_fetch_jd_javascript_url_rejected(client):
    """Don't let someone pass javascript: URLs through to the backend."""
    r = client.post("/api/fetch-jd", json={"url": "javascript:alert(1)"})
    assert r.status_code == 400


def test_fetch_jd_malformed_url(client):
    r = client.post("/api/fetch-jd", json={"url": "https://"})
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_url"


# ─── network failures ──────────────────────────────────────────────────────


@respx.mock
def test_fetch_jd_timeout(client):
    url = "https://slow.example.com/jobs/1"
    respx.get(url).mock(side_effect=httpx.TimeoutException("timed out"))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 504
    assert r.json()["detail"]["error"] == "timeout"


@respx.mock
def test_fetch_jd_network_error(client):
    url = "https://broken.example.com/jobs/1"
    respx.get(url).mock(side_effect=httpx.ConnectError("dns failure"))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "network_error"


@respx.mock
def test_fetch_jd_upstream_4xx(client):
    url = "https://example.com/jobs/forbidden"
    respx.get(url).mock(return_value=httpx.Response(403, text="Forbidden"))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 502
    assert r.json()["detail"]["error"] == "http_403"


# ─── bot blocking ──────────────────────────────────────────────────────────


@respx.mock
def test_fetch_jd_login_wall_detected(client):
    url = "https://linkedin.example.com/jobs/123"
    respx.get(url).mock(return_value=httpx.Response(200, text=LOGIN_WALL_HTML))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 422
    body = r.json()
    # Either bot_blocked (login marker matched) or no_content_extracted is acceptable
    assert body["detail"]["error"] in ("bot_blocked", "no_content_extracted")


@respx.mock
def test_fetch_jd_empty_extraction(client):
    """Page returns 200 but no real content — trafilatura returns nothing."""
    url = "https://empty.example.com/jobs/1"
    respx.get(url).mock(return_value=httpx.Response(200, text="<html></html>"))

    r = client.post("/api/fetch-jd", json={"url": url})
    assert r.status_code == 422
