"""2.1.0: data folder rename encorlab -> cml-lab-builder, moved automatically on the first start."""
import json
import os
import sys
import time
import types

import pytest

from cmllab import config, paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    for k in ("CMLLAB_DATA_DIR", "CMLLAB_SETTINGS_FILE", "CMLLAB_DATA_DIR", "CMLLAB_SETTINGS_FILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    paths.reset_cache()
    yield tmp_path
    paths.reset_cache()


def old_install(home):
    old = home / "encorlab"
    (old / "labs").mkdir(parents=True)
    (old / "settings.json").write_text(json.dumps({"cml_url": "https://cml.x", "username": "dylan"}))
    (old / "labs" / "mine.encorlab").write_bytes(b"PK\x03\x04 a pack")
    (old / "history.jsonl").write_text('{"lab": "01"}\n')
    (old / "app" / "versions" / "2.0.0" / "encorlab").mkdir(parents=True)
    (old / "app" / "state.json").write_text('{"current": "2.0.0"}')
    return old


def test_move_copies_everything_but_app_and_leaves_the_old_folder(home):
    old = old_install(home)
    rec = paths.ensure_moved()
    new = home / "cml-lab-builder"
    assert rec["state"] == "moved" and rec["files"] == 3 and rec["notified"] is False and rec["boot_dirs_left"] == ["app"]
    assert (new / "labs" / "mine.encorlab").read_bytes() == b"PK\x03\x04 a pack"
    assert json.loads((new / "settings.json").read_text())["username"] == "dylan"
    assert not (new / "app").exists()                                  # the boot loader keeps app/ in the old folder
    assert (old / "settings.json").is_file() and (old / "app" / "state.json").is_file()   # nothing deleted
    moved = (old / "MOVED.txt").read_text()
    assert str(new) in moved and "app\nfolder" in moved
    assert paths.data_dir() == new and config.settings_file() == new / "settings.json"
    assert not list(home.glob(".cml-lab-builder.moving-*"))


def test_move_is_idempotent_and_catches_up_files_written_by_the_old_app(home):
    old = old_install(home)
    first = paths.ensure_moved()
    new = home / "cml-lab-builder"
    (new / "labs" / "mine.encorlab").unlink()                          # deleted in the new version
    (new / "settings.json").write_text('{"username": "changed"}')
    paths.reset_cache()
    again = paths.ensure_moved()
    assert again["at"] == first["at"] and again["new_files"] == []
    assert not (new / "labs" / "mine.encorlab").exists()               # deleted labs do not come back
    # the old app (after a rollback to 2.0.0) writes a new lab and changes settings
    time.sleep(0.05)
    (old / "labs" / "later.encorlab").write_bytes(b"new")
    os.utime(old / "settings.json")
    paths.reset_cache()
    rec = paths.ensure_moved()
    assert rec["new_files"] == ["labs/later.encorlab"] and (new / "labs" / "later.encorlab").read_bytes() == b"new"
    assert json.loads((new / "settings.json").read_text())["username"] == "changed"      # never overwritten
    assert paths.status()["caught_up"] == ["labs/later.encorlab"]


def test_fresh_install_and_only_app_in_old_folder(home):
    (home / "encorlab" / "app").mkdir(parents=True)
    (home / "encorlab" / "app" / "state.json").write_text("{}")
    rec = paths.ensure_moved()
    assert rec["state"] == "fresh" and (home / "cml-lab-builder").is_dir()
    assert not (home / "encorlab" / "MOVED.txt").exists()


def test_existing_new_folder_is_merged_without_overwriting(home):
    old_install(home)
    new = home / "cml-lab-builder"
    new.mkdir()
    (new / "settings.json").write_text('{"username": "hand-made"}')
    rec = paths.ensure_moved()
    assert rec["state"] == "moved" and rec["kept_existing"] == ["settings.json"]
    assert json.loads((new / "settings.json").read_text())["username"] == "hand-made"
    assert (new / "history.jsonl").is_file()


def test_failed_copy_keeps_using_the_old_folder(home, monkeypatch):
    old = old_install(home)
    monkeypatch.setattr(paths, "_sha", lambda p: str(p))              # every check "fails"
    rec = paths.ensure_moved()
    assert rec["state"] == "failed" and "copy check failed" in rec["error"]
    assert paths.data_dir() == old and not (home / "cml-lab-builder").exists()
    assert not list(home.glob(".cml-lab-builder.moving-*"))
    monkeypatch.undo()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    paths.reset_cache()
    assert paths.ensure_moved()["state"] == "moved"                    # retried on the next start


def test_concurrent_start_uses_the_other_process_result(home, monkeypatch):
    old_install(home)
    real = os.replace
    new = home / "cml-lab-builder"

    def racing(src, dst):
        if str(dst) == str(new) and ".moving-" in str(src):
            other = new.with_name(".other")
            real(src, other)                                           # pretend another process won
            real(other, new)
            raise OSError("exists")
        return real(src, dst)
    monkeypatch.setattr(os, "replace", racing)
    rec = paths.ensure_moved()
    assert rec["state"] == "moved" and (new / "settings.json").is_file()


def test_interrupted_staging_folder_is_cleaned(home):
    old_install(home)
    left = home / ".cml-lab-builder.moving-999"
    left.mkdir()
    os.utime(left, (time.time() - 3600, time.time() - 3600))
    paths.ensure_moved()
    assert not left.exists()


def test_keyring_password_is_copied_to_the_new_name(home, monkeypatch):
    store = {(config.LEGACY_KEYRING_SERVICE, "dylan"): "pw"}
    kr = types.SimpleNamespace(get_password=lambda s, u: store.get((s, u)),
                               set_password=lambda s, u, p: store.__setitem__((s, u), p))
    monkeypatch.setitem(sys.modules, "keyring", kr)
    old_install(home)
    assert paths.ensure_moved()["keyring"] == "copied"
    assert store[(config.KEYRING_SERVICE, "dylan")] == "pw" and store[(config.LEGACY_KEYRING_SERVICE, "dylan")] == "pw"


def test_pinned_folder_never_moves(home, monkeypatch):
    old_install(home)
    monkeypatch.setenv("CMLLAB_DATA_DIR", str(home / "pinned"))
    assert paths.ensure_moved() == {"state": "pinned"} and paths.data_dir() == home / "pinned"
    assert not (home / "cml-lab-builder").exists()
    monkeypatch.delenv("CMLLAB_DATA_DIR")
    monkeypatch.setenv("CMLLAB_SETTINGS_FILE", str(home / "s" / "settings.json"))
    assert paths.data_dir() == home / "s"


def test_env_prefixes(monkeypatch):
    monkeypatch.delenv("CMLLAB_X_TEST", raising=False)
    monkeypatch.setenv("CMLLAB_X_TEST", "old")
    assert paths.env_get("X_TEST") == "old"
    monkeypatch.setenv("CMLLAB_X_TEST", "new")
    assert paths.env_get("X_TEST") == "new"


def test_acknowledge_and_api(home):
    old_install(home)
    from fastapi.testclient import TestClient

    from cmllab.web.app import create_app
    c = TestClient(create_app(persist=False))
    d = c.get("/api/data-folder").json()
    assert d["state"] == "moved" and d["notified"] is False and d["to"].endswith("cml-lab-builder")
    c.post("/api/data-folder/ack")
    assert c.get("/api/data-folder").json()["notified"] is True
    assert paths.status()["notified"] is True and not paths.status().get("cli_notified")


def test_cli_prints_the_note_once(home):
    from typer.testing import CliRunner

    from cmllab.cli import app
    old_install(home)
    r1 = CliRunner().invoke(app, ["list"])
    assert "data moved" in r1.output.lower() or "data moved" in (r1.stderr if hasattr(r1, "stderr") else "").lower()
    paths.reset_cache()
    r2 = CliRunner().invoke(app, ["list"])
    assert "data moved" not in r2.output.lower()
