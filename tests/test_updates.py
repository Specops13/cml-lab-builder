"""Update checker (GitHub Releases), off by default."""
import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from encorlab import __version__, config, library, updates
from encorlab.cli import app as cli_app
from encorlab.web.app import create_app


def rel(tag, **kw):
    d = {"tag_name": tag, "name": f"ENCOR Lab Builder {tag}", "html_url": f"https://github.com/{updates.REPO}/releases/tag/{tag}",
         "published_at": "2026-10-18T10:00:00Z", "body": "notes",
         "assets": [{"name": "x.zip", "size": 10, "browser_download_url": "https://github.com/a/b/x.zip"},
                    {"name": "evil", "browser_download_url": "http://evil/x"}]}
    d.update(kw)
    raw = json.dumps(d).encode()
    calls = []

    def f(url, limit):
        calls.append(url)
        return raw
    f.calls = calls
    return f


def test_parse_version():
    assert updates.parse_version("v1.5.0") == (1, 5, 0) and updates.parse_version("2.0") == (2, 0, 0)
    assert updates.parse_version("1.10.2-rc1") == (1, 10, 2) and updates.parse_version("latest") is None


@pytest.mark.parametrize("tag,current,avail", [("v1.6.0", "1.5.0", True), ("v1.5.0", "1.5.0", False),
                                               ("v1.4.0", "1.5.0", False), ("v1.10.0", "1.9.3", True)])
def test_check_compares_versions(tag, current, avail):
    f = rel(tag)
    r = updates.check(current, fetch=f)
    assert r["update_available"] is avail and r["latest"] == tag[1:] and f.calls == [updates.LATEST_URL]
    assert [a["name"] for a in r["assets"]] == ["x.zip"]     # only github.com download links are shown


def test_check_sanitizes_and_rejects_bad_responses():
    r = updates.check("1.0.0", fetch=rel("v2.0.0", html_url="https://evil.example/"))
    assert r["url"] == updates.RELEASES_PAGE
    with pytest.raises(library.LibraryError, match="no version tag"):
        updates.check("1.0.0", fetch=rel("nightly"))
    with pytest.raises(library.LibraryError, match="invalid response"):
        updates.check("1.0.0", fetch=lambda u, n: b"<html>")


def test_api_update_check_and_setting_default_on(tmp_path):
    assert config.Settings().check_updates is True
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_fetch=rel("v99.0.0")))
    r = c.get("/api/update-check").json()
    assert r["update_available"] and r["current"] == __version__ and r["latest"] == "99.0.0"
    assert c.get("/api/settings").json()["check_updates"] is True
    assert c.post("/api/settings", json={"check_updates": False}).json()["check_updates"] is False

    def down(u, n):
        raise library.LibraryError("network error fetching x: ConnectError")
    c2 = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, update_fetch=down))
    r = c2.get("/api/update-check")
    assert r.status_code == 502 and "network error" in r.json()["error"] and r.json()["url"] == updates.RELEASES_PAGE


def test_check_updates_is_persisted(tmp_path, monkeypatch):
    f = tmp_path / "s.json"
    monkeypatch.setenv("ENCOR_SETTINGS_FILE", str(f))
    s = config.SettingsStore(config.Settings()).update(check_updates="false")
    config.save_settings(s)
    saved = json.loads(f.read_text())
    assert saved["check_updates"] is False and saved["_format"] == 2 and config.from_env().check_updates is False


def test_old_settings_file_is_migrated_to_auto_updates_on(tmp_path, monkeypatch):
    """1.6 and older always wrote check_updates=false (it was the default), so it is not an explicit opt-out."""
    f = tmp_path / "s.json"
    monkeypatch.setenv("ENCOR_SETTINGS_FILE", str(f))
    f.write_text(json.dumps({"cml_url": "https://cml.lab", "check_updates": False, "show_help": False}))
    s = config.from_env()
    assert s.check_updates is True and s.show_help is False and s.cml_url == "https://cml.lab"
    config.save_settings(s)                                  # the next save records the format ...
    s2 = config.SettingsStore(config.from_env()).update(check_updates=False)
    config.save_settings(s2)
    assert config.from_env().check_updates is False          # ... so an opt-out from now on is kept


def test_cli_update_check(monkeypatch):
    monkeypatch.setattr(updates.check, "__defaults__", (__version__, rel("v99.1.0"), updates.LATEST_URL))
    r = CliRunner().invoke(cli_app, ["update-check"])
    assert r.exit_code == 0 and "Update available: 99.1.0" in r.output
    monkeypatch.setattr(updates.check, "__defaults__", (__version__, rel("v" + __version__), updates.LATEST_URL))
    assert "latest version" in CliRunner().invoke(cli_app, ["update-check"]).output
