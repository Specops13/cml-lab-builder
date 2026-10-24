"""Runtime settings. Sources (lowest -> highest priority): defaults, env vars,
saved secrets (opt-in "remember"), values set at runtime (web Settings page).

Secrets (SECRETS) are never written to settings.json, never logged, masked in repr() and redacted from job logs and
error messages (redact()). "Remember" stores them in the OS keyring (Windows Credential Manager, macOS Keychain,
Secret Service on Linux); only where no keyring exists they go to secrets.json in the data folder, readable by the
user only (0600). settings.json is 0600 too. Secrets found in an old or hand-edited settings.json are moved into the
keyring on load (3.3.0)."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from dataclasses import dataclass, field, fields
from urllib.parse import urlparse

# The default library address up to 2.0.0 (old repo name, old file names). A saved copy of it means "the default".
LEGACY_LIBRARY_URLS = ("https://raw.githubusercontent.com/Specops13/encore-lab-app/main/labs/index.json",)
KEYRING_SERVICE = "cml-lab-builder"
LEGACY_KEYRING_SERVICE = "encorlab-cml"   # before 2.1.0; still read, copied to the new name on the data move
SECRETS = ("password", "device_password", "device_enable", "nxos_password", "ai_api_key")


def _bool_or_path(value: str | None, default: bool | str = True) -> bool | str:
    if value is None or value.strip() == "":
        return default
    v = value.strip()
    if v.lower() in ("1", "true", "yes", "on"):
        return True
    if v.lower() in ("0", "false", "no", "off"):
        return False
    return v  # path to a CA bundle


@dataclass
class Settings:
    cml_url: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    verify_tls: bool | str = True
    console_host: str = ""          # Console server FQDN (SSH / TCP port-22 proxy); default = host of cml_url
    console_port: int = 22
    grading_mode: str = "auto"      # auto (live, fall back to config) | live | config
    console_backend: str = "ssh"    # "ssh" (paramiko, works on Windows) or "pyats" (Linux/macOS)
    platform: str = "iol"           # "iol" (IOL / IOL-L2) or "iosv" (IOSv / IOSvL2)
    node_limit: int = 20
    lab_prefix: str = "CML-"         # CML lab titles (ENCOR- up to 2.1.0; those labs are still recognised)
    boot_timeout: int = 900
    library_url: str = ""           # lab library index (library/index.json); empty = the project's GitHub repo
    ram_heavy_gb: int = 16          # labs estimated at or above this many GB of CML RAM get a red "RAM heavy" tag
    device_username: str = "cisco"
    device_password: str = field(default="cisco", repr=False)
    device_enable: str = field(default="cisco", repr=False)
    nxos_username: str = ""         # NX-OS (nxosv9000) console login and day-0 user; empty = the device username
    nxos_password: str = field(default="", repr=False)   # empty = the device password
    ai_preset: str = ""             # optional AI generator (secondary feature)
    ai_base_url: str = ""
    ai_model: str = ""
    ai_api_key: str = field(default="", repr=False)
    show_help: bool = True          # web UI: show the small "?" help icons
    check_updates: bool = True      # packaged app: check GitHub Releases in the background and offer patch updates

    def __repr__(self) -> str:  # never leak secrets
        parts = []
        for f in fields(self):
            v = getattr(self, f.name)
            if f.name in SECRETS:
                v = "***" if v else ""
            parts.append(f"{f.name}={v!r}")
        return "Settings(" + ", ".join(parts) + ")"

    @property
    def effective_console_host(self) -> str:
        if self.console_host:
            return self.console_host
        return urlparse(self.cml_url if "://" in self.cml_url else "https://" + self.cml_url).hostname or ""

    def is_configured(self) -> bool:
        return bool(self.cml_url and self.username and self.password)

    def public_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        for k in SECRETS:
            d[k] = ""
            d[k + "_set"] = bool(getattr(self, k))
        d["effective_console_host"] = self.effective_console_host
        return d

    def validate(self) -> list[str]:
        errs = []
        if self.platform not in ("iol", "iosv"):
            errs.append("platform must be 'iol' or 'iosv'")
        if self.grading_mode not in ("auto", "live", "config"):
            errs.append("grading_mode must be auto, live or config")
        if not (1 <= int(self.console_port) <= 65535):
            errs.append("console_port must be 1-65535")
        if self.console_backend not in ("ssh", "pyats"):
            errs.append("console_backend must be 'ssh' or 'pyats'")
        if not (1 <= int(self.node_limit) <= 1000):
            errs.append("node_limit must be between 1 and 1000")
        if not (1 <= int(self.ram_heavy_gb) <= 1024):
            errs.append("ram_heavy_gb must be between 1 and 1024")
        if self.library_url:
            u = urlparse(self.library_url)
            if not ((u.scheme == "https" and u.netloc) or (u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"))):
                errs.append("library_url must start with https:// (http:// only for localhost)")
        if self.cml_url and urlparse(self.cml_url).scheme not in ("https", "http"):
            errs.append("cml_url must start with https://")
        if isinstance(self.verify_tls, str) and not Path(self.verify_tls).expanduser().is_file():
            errs.append(f"CA bundle not found: {self.verify_tls} (TLS verification: a PEM file on this computer)")
        return errs


def from_env(env: dict | None = None) -> Settings:
    e = os.environ if env is None else env
    s = Settings()
    s.cml_url = e.get("CML_URL", s.cml_url).rstrip("/")
    s.username = e.get("CML_USERNAME", s.username)
    s.password = e.get("CML_PASSWORD", s.password)
    s.verify_tls = _bool_or_path(e.get("CML_VERIFY_SSL"), True)
    s.console_host = e.get("CML_CONSOLE_HOST", s.console_host)
    s.console_port = int(e.get("CML_CONSOLE_PORT", s.console_port))
    s.console_backend = e.get("CMLLAB_CONSOLE_BACKEND", s.console_backend)
    s.grading_mode = e.get("CMLLAB_GRADING_MODE", s.grading_mode)
    s.platform = e.get("CMLLAB_PLATFORM", s.platform)
    s.node_limit = int(e.get("CMLLAB_NODE_LIMIT", s.node_limit))
    s.lab_prefix = e.get("CMLLAB_LAB_PREFIX", s.lab_prefix)
    s.boot_timeout = int(e.get("CMLLAB_BOOT_TIMEOUT", s.boot_timeout))
    s.ram_heavy_gb = int(e.get("CMLLAB_RAM_HEAVY_GB", s.ram_heavy_gb))
    s.library_url = e.get("CMLLAB_LIBRARY_URL", s.library_url).strip()
    s.device_username = e.get("CMLLAB_DEVICE_USERNAME", s.device_username)
    s.device_password = e.get("CMLLAB_DEVICE_PASSWORD", s.device_password)
    s.device_enable = e.get("CMLLAB_DEVICE_ENABLE", s.device_enable)
    s.nxos_username = e.get("CMLLAB_NXOS_USERNAME", s.nxos_username)
    s.nxos_password = e.get("CMLLAB_NXOS_PASSWORD", s.nxos_password)
    s.ai_base_url = e.get("CMLLAB_AI_BASE_URL", s.ai_base_url)
    s.ai_model = e.get("CMLLAB_AI_MODEL", s.ai_model)
    s.ai_api_key = e.get("CMLLAB_AI_API_KEY", s.ai_api_key)
    for k, v in load_saved(e).items():  # values saved from the Settings page win over env
        if k == "library_url" and (not v or str(v).strip() in LEGACY_LIBRARY_URLS):
            continue                    # empty (or the pre-2.1 default) = "the default", so CMLLAB_LIBRARY_URL still applies
        if k in PERSISTED:
            setattr(s, k, v)
    if e.get("CMLLAB_USE_KEYRING", "1") != "0":
        if env is None:
            migrate_secrets()
        if not s.password and s.username:
            s.password = keyring_get(s.username) or ""
        if not s.ai_api_key and s.ai_base_url:
            s.ai_api_key = keyring_get("ai-key:" + s.ai_base_url) or ""
        for k in ("device_password", "device_enable", "nxos_password"):   # remembered with the CML password (3.3.0)
            if not e.get({"device_password": "CMLLAB_DEVICE_PASSWORD", "device_enable": "CMLLAB_DEVICE_ENABLE",
                          "nxos_password": "CMLLAB_NXOS_PASSWORD"}[k]):
                v = keyring_get("device:" + k)
                if v:
                    setattr(s, k, v)
    return s


# Non-secret settings saved from the web Settings page. Passwords are never written here.
PERSISTED = ("cml_url", "username", "verify_tls", "console_host", "console_port", "grading_mode",
             "platform", "node_limit", "boot_timeout", "ai_preset", "ai_base_url", "ai_model", "show_help",
             "check_updates", "ram_heavy_gb", "library_url", "device_username", "nxos_username")


def settings_file(env=None) -> Path:
    """settings.json in the user data folder (see paths.py; the first call moves an old encorlab folder)."""
    from . import paths
    if paths.env_get("SETTINGS_FILE", env):
        return Path(paths.env_get("SETTINGS_FILE", env))
    return paths.data_dir(env) / "settings.json"


# settings.json format. 2 (1.7.0): automatic update checks are on by default. Files written before (no "_format")
# always contained check_updates=false because that was the default and every save wrote all keys, so an explicit
# opt-out cannot be told apart from the default: those files are migrated to "on" (turn it off again in Settings).
SETTINGS_FORMAT = 2


def load_saved(env=None) -> dict:
    f = settings_file(env)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if int(data.get("_format") or 1) < 2:
        data.pop("check_updates", None)
    return data


def save_settings(s: "Settings", env=None) -> Path:
    f = settings_file(env)
    f.parent.mkdir(parents=True, exist_ok=True)
    data = {"_format": SETTINGS_FORMAT, **{k: getattr(s, k) for k in PERSISTED}}
    _write_private(f, json.dumps(data, indent=2))
    return f


# ---------------------------------------------------------------- secret storage (keyring, else a 0600 file)
SECRETS_FILE = "secrets.json"


def _keyring():
    """The keyring module, or None when there is no usable backend (headless Linux without Secret Service, ...)."""
    try:
        import keyring
        from keyring.backends import fail
        kr = keyring.get_keyring()
        if isinstance(kr, fail.Keyring) or "fail" in type(kr).__module__ or "null" in type(kr).__module__:
            return None
        return keyring
    except Exception:
        return None


def _secrets_file(env=None) -> Path:
    return settings_file(env).parent / SECRETS_FILE


def _write_private(f: Path, text: str) -> None:
    """Write a file only the user can read (0600; on Windows the per-user data folder already is private)."""
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + f".tmp{os.getpid()}")
    tmp.unlink(missing_ok=True)
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def _file_secrets(env=None) -> dict:
    try:
        d = json.loads(_secrets_file(env).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def secret_backend() -> str:
    return "keyring" if _keyring() else "file"


def keyring_get(username: str) -> str | None:
    """A remembered secret (the CML password is stored under the CML username; others under 'ai-key:<url>',
    'device:<name>'). Keyring first (also the pre-2.1 service name), then the 0600 fallback file."""
    kr = _keyring()
    if kr is not None:
        try:
            v = kr.get_password(KEYRING_SERVICE, username) or kr.get_password(LEGACY_KEYRING_SERVICE, username)
            if v:
                return v
        except Exception:
            pass
    v = _file_secrets().get(username)
    return str(v) if v else None


def keyring_set(username: str, password: str) -> bool:
    """Remember a secret: OS keyring, else the 0600 fallback file. True when it was stored."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(KEYRING_SERVICE, username, password)
            _file_forget(username)     # moved into the keyring: drop a fallback copy
            return True
        except Exception:
            pass
    try:
        d = _file_secrets()
        d[username] = password
        _write_private(_secrets_file(), json.dumps(d, indent=1))
        return True
    except OSError:
        return False


def _file_forget(username: str) -> None:
    d = _file_secrets()
    if username in d:
        d.pop(username)
        try:
            if d:
                _write_private(_secrets_file(), json.dumps(d, indent=1))
            else:
                _secrets_file().unlink(missing_ok=True)
        except OSError:
            pass


def migrate_secrets(env=None) -> list[str]:
    """3.3.0: secrets never belong in settings.json. Move any found there (old or hand-edited files) into the secret
    store, rewrite the file without them (0600), and move fallback-file secrets into the keyring once one exists.
    Returns what was moved (names only)."""
    moved = []
    f = settings_file(env)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        user = str(data.get("username") or "")
        found = {k: data.pop(k) for k in list(data) if k in SECRETS}
        for k, v in found.items():
            if v:
                key = user if k == "password" else (("ai-key:" + str(data.get("ai_base_url") or "")) if k == "ai_api_key" else "device:" + k)
                if (k != "password" or user) and keyring_set(key, str(v)):
                    moved.append(k)
        if found:
            try:
                _write_private(f, json.dumps(data, indent=2))
            except OSError:
                pass
    if _keyring() is not None:
        for k, v in list(_file_secrets(env).items()):
            try:
                _keyring().set_password(KEYRING_SERVICE, k, str(v))
                _file_forget(k)
                moved.append(k)
            except Exception:
                pass
    return moved


# ---------------------------------------------------------------- never log secrets
_KNOWN: set[str] = set()
_KV = re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|authorization)(\s*[=:]\s*)(bearer\s+)?([^\s,;&\"']+)")


def remember_for_redaction(*values) -> None:
    for v in values:
        if isinstance(v, str) and len(v) >= 4:
            _KNOWN.add(v)


def redact(text) -> str:
    """Remove secrets from a message: known secret values (current settings) and key=value / 'password xyz' forms."""
    s = str(text)
    for v in sorted(_KNOWN, key=len, reverse=True):
        if v in s:
            s = s.replace(v, "***")
    return _KV.sub(lambda m: m.group(1) + m.group(2) + (m.group(3) or "") + "***", s)


class SettingsStore:
    """Thread-safe holder used by the web UI and CLI."""

    def __init__(self, settings: Settings | None = None):
        self._lock = threading.RLock()
        self._s = settings or from_env()

    def get(self) -> Settings:
        with self._lock:
            remember_for_redaction(*(getattr(self._s, k) for k in SECRETS if k not in ("device_password", "device_enable")
                                     or getattr(self._s, k) != "cisco"))
            return Settings(**{f.name: getattr(self._s, f.name) for f in fields(Settings)})

    def update(self, **kw) -> Settings:
        with self._lock:
            new = Settings(**{f.name: getattr(self._s, f.name) for f in fields(Settings)})
            for k, v in kw.items():
                if not hasattr(new, k):
                    raise ValueError(f"unknown setting {k}")
                if k in SECRETS and v in (None, ""):
                    continue  # empty = keep existing secret
                if k in ("console_port", "node_limit", "boot_timeout", "ram_heavy_gb"):
                    v = int(v)
                if k == "verify_tls" and isinstance(v, str):
                    v = _bool_or_path(v, True)
                if k in ("show_help", "check_updates"):
                    v = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
                if k == "library_url":
                    v = str(v or "").strip()
                if k == "cml_url" and isinstance(v, str):
                    v = v.strip().rstrip("/")
                setattr(new, k, v)
            errs = new.validate()
            if errs:
                raise ValueError("; ".join(errs))
            self._s = new
            return self.get()
