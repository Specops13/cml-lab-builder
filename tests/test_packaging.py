"""Packaging: launcher behaviour and build files (the frozen build itself is smoke-tested by packaging/smoke_test.py)."""
import re
import socket
import threading
import urllib.request
from pathlib import Path

from encorlab import __version__, launcher

ROOT = Path(__file__).resolve().parents[1]


def test_app_js_version_matches_package():
    js = (ROOT / "encorlab" / "web" / "static" / "app.js").read_text(encoding="utf-8")
    assert re.search(r'const APP_JS_VERSION = "([^"]+)"', js).group(1) == __version__
    assert "versionCheck" in js and "visibilitychange" in js


def test_parse_args():
    assert launcher._parse([]) == ({"port": 8765, "browser": True}, None)
    assert launcher._parse(["--port", "9000", "--no-browser"]) == ({"port": 9000, "browser": False}, None)
    assert launcher._parse(["--port=9001"])[0]["port"] == 9001
    assert launcher._parse(["list"])[1] == ["list"]
    assert launcher._parse(["check", "eigrp-basic", "--mode", "config"])[1] == ["check", "eigrp-basic", "--mode", "config"]
    assert launcher._parse(["--help"])[1] == ["--help"]


def test_bind_socket_is_loopback_and_skips_busy_port():
    first = launcher.bind_socket(0)          # any free port
    busy = first.getsockname()[1]
    try:
        s = launcher.bind_socket(busy, span=5)
        try:
            host, port = s.getsockname()
            assert host == "127.0.0.1" and port != busy
        finally:
            s.close()
    finally:
        first.close()


def test_serve_and_detect_running_instance(capsys):
    probe = socket.socket(); probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
    ready = threading.Event()
    threading.Thread(target=launcher.serve, kwargs={"port": port, "browser": False, "ready": ready}, daemon=True).start()
    assert ready.wait(20)
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=5) as r:
        assert __version__ in r.read().decode()
    assert launcher._running_instance(port) == __version__
    assert launcher.serve(port, browser=False) == 0          # second launch just points at the running one
    assert "already running" in capsys.readouterr().out


def test_cli_passthrough(capsys):
    assert launcher.main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_build_files_present_and_consistent():
    pk = ROOT / "packaging"
    for f in ("encorlab.spec", "build.py", "build_exe.bat", "build_linux.sh", "smoke_test.py", "README-BINARY.txt",
              "encorlab.ico", "encorlab.png", "install-desktop-entry.sh"):
        assert (pk / f).is_file(), f
    spec = (pk / "encorlab.spec").read_text(encoding="utf-8")
    assert 'collect_data_files("encorlab"' in spec and "exclude_binaries=True" in spec and "upx=False" in spec
    assert b"\r\n" in (pk / "build_exe.bat").read_bytes()               # cmd.exe wants CRLF
    wf = (ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8")
    assert "windows-latest" in wf and "ubuntu-22.04" in wf and "--smoke" in wf
    assert "overwrite_files: false" in wf and "github.event_name == 'workflow_dispatch'" in wf  # tag push never re-publishes
    assert (ROOT / "encor_launcher.py").read_text(encoding="utf-8").count("from encorlab.launcher import main") == 1


def test_frozen_paths_are_package_relative():
    """Data files are found next to the modules, which PyInstaller preserves (collect_data_files)."""
    from encorlab import catalog, prompt
    from encorlab.web import app
    assert catalog.LABS_DIR.parent == Path(catalog.__file__).parent
    assert prompt.RES.parent == Path(prompt.__file__).parent and app.HERE == Path(app.__file__).parent
