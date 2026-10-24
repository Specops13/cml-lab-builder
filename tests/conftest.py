import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
# The app ships without labs (they come from the online library). The suite uses the lab sources in labsrc/
# in place, as read-only "built-in" labs (see catalog.LABS_DIR); tests of the empty first run point it elsewhere.
LABSRC = Path(__file__).resolve().parents[1] / "labsrc"
os.environ["CMLLAB_BUILTIN_LABS_DIR"] = str(LABSRC)

from cmllab.config import Settings  # noqa: E402


@pytest.fixture
def settings():
    return Settings(cml_url="https://cml.example.ts.net", username="dylan", password="s3cret",
                    node_limit=20, boot_timeout=60)


@pytest.fixture(autouse=True)
def _isolated_user_dirs(tmp_path, monkeypatch):
    """Never touch the real user config/labs folders during tests."""
    monkeypatch.setenv("CMLLAB_USER_LABS_DIR", str(tmp_path / "userlabs"))
    monkeypatch.setenv("CMLLAB_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CMLLAB_USE_KEYRING", "0")


@pytest.fixture(autouse=True)
def _isolated_config_home(tmp_path_factory, monkeypatch):
    """Never touch the real ~/.config (or %APPDATA%): every test gets its own config home, and the console
    driver's waits are shortened for the scripted fake consoles."""
    home = tmp_path_factory.mktemp("cfg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("APPDATA", str(home))
    from cmllab import console, paths
    paths.reset_cache()
    monkeypatch.setattr(console, "OPEN_WAIT", 0.3)
    yield
    paths.reset_cache()


@pytest.fixture(autouse=True)
def _trust_test_signing_key(monkeypatch):
    """Updates must be signed (signing.py); the suite signs fake releases with a throwaway key from fakes.py."""
    from cmllab import signing
    from fakes import TEST_PUB_HEX
    monkeypatch.setattr(signing, "TRUSTED_KEYS", {**signing.TRUSTED_KEYS, "test": TEST_PUB_HEX})


@pytest.fixture(autouse=True)
def _web_client_defaults(monkeypatch):
    """The web UI refuses unknown Host headers and state-changing requests without the CSRF header (web/security.py).
    Test clients talk to http://testserver and act like the app's own page (app.js sends X-CMLLab-Request: 1);
    tests/test_web_security.py checks the refusals with the header removed."""
    monkeypatch.setenv("CMLLAB_ALLOWED_HOSTS", "testserver")
    from starlette.testclient import TestClient
    orig = TestClient.__init__

    def init(self, *a, **kw):
        orig(self, *a, **kw)
        self.headers.setdefault("X-CMLLab-Request", "1")
    monkeypatch.setattr(TestClient, "__init__", init)
