import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from encorlab.config import Settings  # noqa: E402


@pytest.fixture
def settings():
    return Settings(cml_url="https://cml.example.ts.net", username="dylan", password="s3cret",
                    node_limit=20, boot_timeout=60)


@pytest.fixture(autouse=True)
def _isolated_user_dirs(tmp_path, monkeypatch):
    """Never touch the real user config/labs folders during tests."""
    monkeypatch.setenv("ENCOR_USER_LABS_DIR", str(tmp_path / "userlabs"))
    monkeypatch.setenv("ENCOR_SETTINGS_FILE", str(tmp_path / "settings.json"))
    monkeypatch.setenv("ENCOR_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ENCOR_USE_KEYRING", "0")
