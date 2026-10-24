"""3.3.0 security hardening: web UI guards (Host allowlist, CSRF, CORS, access token, headers), update signatures,
secret storage and redaction, import safety."""
import json
import os
import stat
import sys

import pytest
from fastapi.testclient import TestClient

import fakes
from cmllab import config, packs, signing
from cmllab.paths import safe_name
from cmllab.web import security
from cmllab.web.app import create_app


def _client(token=None, csrf=True, **kw):
    c = TestClient(create_app(config.SettingsStore(config.Settings()), persist=False, access_token=token, **kw))
    if not csrf:
        c.headers.pop("X-CMLLab-Request", None)
    return c


# ------------------------------------------------------------------ Host allowlist (DNS rebinding)
@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "[::1]:8765", "testserver"])
def test_loopback_hosts_allowed(host):
    assert _client().get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8765", "127.0.0.1.evil.example", ""])
def test_unknown_host_refused(host):
    r = _client().get("/api/settings", headers={"host": host})
    assert r.status_code == 421 and "DNS rebinding" in r.json()["detail"]


def test_extra_allowed_host():
    assert _client(allowed_hosts=("10.0.0.5",)).get("/api/health", headers={"host": "10.0.0.5:8765"}).status_code == 200


# ------------------------------------------------------------------ CSRF / CORS
def test_post_without_csrf_header_refused():
    r = _client(csrf=False).post("/api/settings", json={})
    assert r.status_code == 403 and "CSRF" in r.json()["detail"]


def test_post_from_other_origin_refused():
    r = _client().post("/api/settings", json={}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403


def test_post_same_origin_passes_guard():
    r = _client().post("/api/settings", json={"cml_url": "https://cml.example"}, headers={"origin": "http://testserver"})
    assert r.status_code not in (401, 403, 421)


def test_cross_site_fetch_refused_even_for_get():
    r = _client().get("/api/settings", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403


def test_no_cors():
    c = _client()
    r = c.options("/api/settings", headers={"origin": "https://evil.example", "access-control-request-method": "POST"})
    assert r.status_code == 403
    r = c.get("/api/health", headers={"origin": "https://evil.example"})
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


# ------------------------------------------------------------------ headers
def test_security_headers_everywhere():
    c = _client()
    for path in ("/", "/api/health", "/static/app.js", "/nope"):
        h = c.get(path).headers
        csp = h["content-security-policy"]
        assert "script-src 'self'" in csp and "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
        assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
        assert h["x-content-type-options"] == "nosniff"
        assert h["x-frame-options"] == "DENY"
        assert h["referrer-policy"] == "no-referrer"


def test_index_has_no_inline_script():
    import re
    html = _client().get("/").text
    for m in re.finditer(r"<script\b([^>]*)>(.*?)</script>", html, re.S):
        assert "src=" in m.group(1) and not m.group(2).strip(), m.group(0)[:80]
    assert not re.search(r"\son[a-z]+\s*=", html), "inline event handler"


def test_path_traversal_refused():
    c = _client()
    assert c.get("/api/history/..\\..\\settings").status_code == 400
    assert c.get("/api/history/..%5C..%5Csettings").status_code == 400
    assert c.get("/api/history/a%00b").status_code == 400
    with pytest.raises(ValueError):
        safe_name("../x")
    with pytest.raises(ValueError):
        safe_name("a\\b")
    assert safe_name("ospf-basics") == "ospf-basics"


# ------------------------------------------------------------------ access token
def test_token_required():
    c = _client(token="t" * 32)
    assert c.get("/api/settings").status_code == 401
    page = c.get("/")
    assert page.status_code == 401 and "<script" not in page.text
    assert c.get("/api/health").status_code == 200          # public
    assert c.get("/static/app.js").status_code == 200       # public
    assert c.get("/api/settings", headers={"authorization": "Bearer " + "x" * 32}).status_code == 401


def test_token_link_sets_cookie():
    tok = "t" * 32
    c = _client(token=tok)
    r = c.get(f"/?token={tok}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert c.get("/api/settings").status_code == 200       # cookie kept by the client
    assert c.get("/?token=wrong", follow_redirects=False).status_code == 200   # cookie still valid, no redirect


def test_bearer_token():
    tok = "t" * 32
    assert _client(token=tok).get("/api/settings", headers={"authorization": f"Bearer {tok}"}).status_code == 200


def test_launch_token_file_private(tmp_path, monkeypatch):
    from cmllab import launcher
    monkeypatch.delenv("CMLLAB_ACCESS_TOKEN", raising=False)
    tok, new = launcher.launch_token(reuse=False)
    assert new and len(tok) >= 32
    f = launcher._token_file()
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert launcher.launch_token(reuse=True) == (tok, False)
    monkeypatch.setenv("CMLLAB_ACCESS_TOKEN", "0")
    assert launcher.launch_token(reuse=False)[0] is None


# ------------------------------------------------------------------ update signatures
def test_pure_verify_matches_cryptography():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    for msg in (b"", b"abc", os.urandom(1000)):
        sig = k.sign(msg)
        assert signing.ed25519_verify(pub, msg, sig)
        assert not signing.ed25519_verify(pub, msg + b"x", sig)
        bad = bytearray(sig); bad[5] ^= 1
        assert not signing.ed25519_verify(pub, msg, bytes(bad))


def test_sign_roundtrip_with_pem(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    k = Ed25519PrivateKey.generate()
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    sig = signing.sign(pem, b"data")
    with pytest.raises(signing.SignatureError, match="unknown key"):
        signing.verify(b"data", sig)
    monkeypatch.setattr(signing, "TRUSTED_KEYS", {"x": pub.hex()})
    assert signing.verify(b"data", sig) == signing.key_id(pub)


def test_verify_rejects_unsigned_tampered_and_garbage():
    data = b"sums"
    good = fakes.sign(data)
    assert signing.verify(data, good)
    with pytest.raises(signing.SignatureError, match="not signed"):
        signing.verify(data, None)
    with pytest.raises(signing.SignatureError, match="not valid"):
        signing.verify(data + b"!", good)
    with pytest.raises(signing.SignatureError, match="format"):
        signing.verify(data, b"{not json")
    with pytest.raises(signing.SignatureError, match="too large"):
        signing.verify(data, b" " * (signing.MAX_SIG_BYTES + 1))


def test_release_key_embedded():
    assert any(len(v) == 64 for v in signing.TRUSTED_KEYS.values())
    assert "48f799c3e8938c8be616cde0c4c8bf1927aeea8ab9f5b8cd310efa04e294c6be" in signing.TRUSTED_KEYS.values()


def test_test_key_env_only_for_loopback_update_url(monkeypatch):
    monkeypatch.setattr(signing, "TRUSTED_KEYS", {"release": "00" * 32})
    monkeypatch.setenv(signing.TEST_KEY_ENV, fakes.TEST_PUB_HEX)
    monkeypatch.setenv("CMLLAB_UPDATE_URL", "https://evil.example/releases")
    with pytest.raises(signing.SignatureError):
        signing.verify(b"x", fakes.sign(b"x"))
    monkeypatch.setenv("CMLLAB_UPDATE_URL", "http://127.0.0.1:9/none")
    assert signing.verify(b"x", fakes.sign(b"x"))


def test_no_private_key_in_repo():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for p in root.rglob("*"):
        if {".git", "venv", ".venv", "__pycache__", "build", "dist"} & set(p.parts) or not p.is_file() \
                or p.stat().st_size > 2_000_000 or p.suffix == ".pyc":
            continue
        try:
            assert b"BEGIN PRIVATE" + b" KEY" not in p.read_bytes(), p
        except OSError:
            pass


# ------------------------------------------------------------------ secrets
def test_secrets_fallback_file_is_private(monkeypatch):
    monkeypatch.setattr(config, "_keyring", lambda: None)
    assert config.keyring_set("device:device_password", "hunter22")
    f = config._secrets_file()
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert config.keyring_get("device:device_password") == "hunter22"
    config._file_forget("device:device_password")
    assert config.keyring_get("device:device_password") is None


class _FakeKeyring:
    def __init__(self):
        self.d = {}

    def get_password(self, svc, user):
        return self.d.get((svc, user))

    def set_password(self, svc, user, pw):
        self.d[(svc, user)] = pw


def test_migrate_secrets_out_of_settings_json(monkeypatch):
    kr = _FakeKeyring()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    f = config.settings_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"cml_url": "https://c", "username": "dylan", "password": "pw-in-file",
                             "device_password": "dev-pw"}))
    moved = config.migrate_secrets()
    assert set(moved) >= {"password", "device_password"}
    left = json.loads(f.read_text())
    assert "password" not in left and "device_password" not in left and left["cml_url"] == "https://c"
    assert kr.d[(config.KEYRING_SERVICE, "dylan")] == "pw-in-file"
    assert kr.d[(config.KEYRING_SERVICE, "device:device_password")] == "dev-pw"
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_migrate_file_secrets_into_keyring(monkeypatch):
    monkeypatch.setattr(config, "_keyring", lambda: None)
    config.keyring_set("dylan", "pw1")
    kr = _FakeKeyring()
    monkeypatch.setattr(config, "_keyring", lambda: kr)
    assert "dylan" in config.migrate_secrets()
    assert kr.d[(config.KEYRING_SERVICE, "dylan")] == "pw1" and not config._secrets_file().exists()


def test_settings_json_never_holds_secrets():
    s = config.Settings(cml_url="https://c", username="u", password="pw-xyz", ai_api_key="sk-abcdef")
    f = config.save_settings(s)
    text = f.read_text()
    assert "pw-xyz" not in text and "sk-abcdef" not in text
    if os.name != "nt":
        assert stat.S_IMODE(f.stat().st_mode) == 0o600


def test_redaction():
    config.remember_for_redaction("Sup3rSecret!")
    out = config.redact("login failed for dylan / Sup3rSecret! api_key=sk-123456 Authorization: Bearer abc.def token=xyz")
    assert "Sup3rSecret!" not in out and "sk-123456" not in out and "abc.def" not in out and "xyz" not in out
    assert "dylan" in out
    ios = "username admin password cisco\nenable secret 5 $1$abc"
    assert "password cisco" in config.redact(ios)   # device config text stays readable


def test_job_errors_redacted():
    import time
    from cmllab.service import JobManager
    config.remember_for_redaction("JobSecret99")
    jm = JobManager()

    def boom(progress):
        progress("connecting with JobSecret99")
        raise RuntimeError("auth failed password=JobSecret99")
    job = jm.start("build", "lab-x", boom)
    for _ in range(200):
        if job.state != "running":
            break
        time.sleep(0.01)
    assert job.state != "running"
    dump = json.dumps(vars(job), default=str)
    assert "JobSecret99" not in dump and "auth failed" in dump


# ------------------------------------------------------------------ TLS
def test_tls_ca_bundle_validated(tmp_path):
    s = config.Settings(cml_url="https://c", username="u", password="p", verify_tls=str(tmp_path / "missing.pem"))
    assert any("CA bundle" in e for e in s.validate())
    ca = tmp_path / "ca.pem"; ca.write_text("-----BEGIN CERTIFICATE-----\n")
    s = config.Settings(cml_url="https://c", username="u", password="p", verify_tls=str(ca))
    assert not any("CA bundle" in e for e in s.validate())
    assert config.Settings().verify_tls is True       # on by default


def test_tls_ui_controls():
    html = _client().get("/").text
    assert 'name="tls_ca"' in html and 'id="tls-warn"' in html and 'value="ca"' in html


# ------------------------------------------------------------------ import safety
@pytest.mark.parametrize("name", ["../x.yaml", "a/../../x", "/etc/passwd", "C:/x", "a\\..\\..\\x", "..\\x", "a\x00b"])
def test_zip_slip_names_rejected(name):
    from cmllab import updates
    assert not packs._safe_member(name)
    assert not updates._safe_member(name)


def test_zip_pack_with_traversal_rejected():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("lab.yaml", "id: x\n")
        z.writestr("../evil.txt", "x")
    with pytest.raises(packs.LabError):
        packs.read_upload("x.zip", buf.getvalue())
