"""Regression tests for v1.3.0 on Windows: stale cached JS/CSS after an upgrade, wrong MIME types, a lab list
that could fail as a whole."""
import mimetypes

from fastapi.testclient import TestClient

from encorlab import __version__, catalog, config
from encorlab.web import app as webapp
from encorlab.web.app import create_app


def client(settings=None):
    return TestClient(create_app(config.SettingsStore(settings or config.Settings()), persist=False))


def test_static_urls_are_versioned():
    html = client().get("/").text
    for asset in ("style.css", "help.js", "app.js"):
        assert f"/static/{asset}?v={__version__}" in html
    assert f'window.APP_VERSION = "{__version__}"' in html
    assert 'id="error-banner"' in html and "{{VERSION}}" not in html


def test_no_cache_headers_on_html_static_and_api():
    c = client()
    for url in ("/", f"/static/app.js?v={__version__}", "/static/style.css", "/static/help.json", "/api/labs", "/api/health"):
        r = c.get(url)
        assert r.status_code == 200, url
        assert "no-cache" in r.headers.get("cache-control", ""), url


def test_correct_mime_even_if_registry_says_text_plain(monkeypatch):
    # simulate a polluted Windows registry: everything guessed as text/plain
    real = mimetypes.guess_type

    def bad(url, strict=True):
        if str(url).split("?")[0].endswith((".js", ".css", ".json")):
            return ("text/plain", None)
        return real(url, strict)
    import starlette.responses as sr
    monkeypatch.setattr(sr, "guess_type", bad)
    c = client()
    assert c.get("/static/app.js").headers["content-type"].startswith("text/javascript")
    assert c.get("/static/help.js").headers["content-type"].startswith("text/javascript")
    assert c.get("/static/style.css").headers["content-type"].startswith("text/css")
    assert c.get("/static/help.json").headers["content-type"].startswith("application/json")


def test_mimetypes_registered_at_import():
    assert webapp.mimetypes.guess_type("x.js")[0] == "text/javascript"
    assert webapp.mimetypes.guess_type("x.css")[0] == "text/css"


def test_labs_list_survives_broken_and_bad_settings(monkeypatch):
    bad = catalog.user_labs_dir() / "broken"
    bad.mkdir(parents=True)
    (bad / "lab.yaml").write_text("id: [", encoding="utf-8")
    s = config.Settings()
    s.platform = "iol\r"   # e.g. a CRLF .env value that bypassed validation
    data = client(s).get("/api/labs").json()
    assert len(data["labs"]) == 11 and "settings" in data["broken"] and any("broken" in k for k in data["broken"])


def test_frontend_resilience_hooks_present():
    c = client()
    js = c.get("/static/app.js").text
    assert 'addEventListener("unhandledrejection"' in js and "Could not load the lab list" in js and "Startup step" in js
    assert "continuing without it" in c.get("/static/help.js").text
