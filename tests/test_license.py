"""MIT license metadata and the THIRD-PARTY-NOTICES generator (packaging/third_party_notices.py)."""
from __future__ import annotations

import importlib.metadata as md
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging"))
import third_party_notices as tpn  # noqa: E402


def test_mit_license_file_and_metadata():
    lic = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert lic.startswith("MIT License\n\nCopyright (c) 2026 Dylan Vaughan (Specops13)\n")
    assert "Permission is hereby granted, free of charge" in lic and 'THE SOFTWARE IS PROVIDED "AS IS"' in lic
    tomllib = pytest.importorskip("tomllib")                          # Python 3.11+
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert py["project"]["license"] == "MIT" and py["project"]["license-files"] == ["LICENSE"]
    assert any(r.startswith("setuptools>=77") for r in py["build-system"]["requires"])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## License" in readme and "badge/license-MIT" in readme and "LGPL-2.1" in readme


def test_build_ships_license_and_notices():
    build = (ROOT / "packaging" / "build.py").read_text(encoding="utf-8")
    assert '"LICENSE.txt"' in build and "third_party_notices.py" in build and "THIRD-PARTY-NOTICES.txt" in build


def _work_with(tmp: Path, *dists: str) -> Path:
    """A fake PyInstaller workpath whose PYZ table lists one module file of each distribution."""
    entries = []
    for name in dists:
        d = md.distribution(name)
        f = next(f for f in d.files if str(f).endswith(".py"))
        entries.append((str(f).replace("/", ".")[:-3], str(d.locate_file(f)), "PYMODULE"))
    (tmp / "PYZ-00.toc").write_text(repr(("PYZ-00.pyz", entries)), encoding="utf-8")
    return tmp


def test_notices_list_exactly_the_bundled_packages(tmp_path):
    rows = tpn.inventory(_work_with(tmp_path, "fastapi", "paramiko", "virl2_client"))
    names = {r["name"].lower().replace("_", "-") for r in rows}
    assert {"fastapi", "paramiko", "virl2-client"} <= names
    assert "pytest" not in names and "encorlab" not in names            # installed, but not bundled / the app
    assert rows[0]["name"].startswith("Python") and rows[0]["license"] == "PSF-2.0"
    by = {r["name"].lower(): r for r in rows}
    assert "LGPL" in by["paramiko"]["license"] and by["paramiko"]["texts"]
    assert tpn.concerns(rows) == []
    text = tpn.render(rows, "1.8.1", "linux")
    assert "MIT License (see LICENSE)" in text and "GNU LESSER GENERAL PUBLIC LICENSE" in text
    assert "https://github.com/paramiko/paramiko" in text or "paramiko.org" in text


def test_license_check_flags_strong_copyleft_and_unknown():
    row = lambda lic, texts=(("LICENSE", "x"),): {"name": "x", "version": "1", "license": lic, "texts": list(texts)}
    assert tpn.concerns([row("GPL-3.0-only")]) and tpn.concerns([row("AGPL-3.0")]) and tpn.concerns([row("UNKNOWN")])
    assert tpn.concerns([row("GNU General Public License v2 (GPLv2)")])
    assert tpn.concerns([row("MIT", texts=())])                         # no license text to ship
    assert not tpn.concerns([row("LGPL-2.1"), row("MPL-2.0"), row("Apache-2.0 OR BSD-3-Clause"),
                             row(tpn.OVERRIDE["pyinstaller"])])
