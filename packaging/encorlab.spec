# PyInstaller spec for ENCOR Lab Builder (one-folder build). Used by build_exe.bat, build_linux.sh and CI.
#   pyinstaller --noconfirm --clean packaging/encorlab.spec
# One-folder (not one-file): starts faster, never unpacks to %TEMP%, and triggers far fewer antivirus heuristics.
import os
import re
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

HERE = os.path.abspath(SPECPATH)  # noqa: F821 (provided by PyInstaller)
ROOT = os.path.dirname(HERE)
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "encorlab", "__init__.py"), encoding="utf-8").read()).group(1)
nums = (tuple(int(x) for x in re.findall(r"\d+", VERSION)[:3]) + (0, 0, 0))[:4]
VERSION_FILE = os.path.join(HERE, "version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as fh:
    fh.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={nums}, prodvers={nums}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'ENCOR Lab Builder'),
    StringStruct('FileDescription', 'ENCOR Lab Builder for Cisco Modeling Labs'),
    StringStruct('FileVersion', '{VERSION}'),
    StringStruct('InternalName', 'ENCORLab'),
    StringStruct('OriginalFilename', 'ENCORLab.exe'),
    StringStruct('ProductName', 'ENCOR Lab Builder'),
    StringStruct('ProductVersion', '{VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")

datas = collect_data_files("encorlab", excludes=["**/__pycache__/**"])
hiddenimports = (
    collect_submodules("encorlab")
    + collect_submodules("uvicorn")
    + collect_submodules("keyring.backends")
    + ["multipart", "python_multipart", "email_validator"]
)
for dist in ("virl2_client", "keyring", "fastapi", "pydantic", "uvicorn", "typer", "encorlab", "paramiko"):
    try:
        datas += copy_metadata(dist)
    except Exception:
        pass

a = Analysis(
    [os.path.join(ROOT, "encor_launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "matplotlib", "numpy", "pyats", "genie"],
    noarchive=False,
)
if sys.platform.startswith("linux"):
    # Use the target system's own GCC runtime: the build host's copy can require a newer glibc than the rest
    # of the bundle (glibc 2.28 baseline). Every glibc-based distro ships libgcc_s.so.1.
    a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).startswith(("libgcc_s.so", "libstdc++.so"))]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="ENCORLab",
    console=True,          # the console window is the "quit" control: close it or press Ctrl+C
    upx=False,             # UPX-packed binaries are a classic antivirus false-positive trigger
    icon=os.path.join(HERE, "encorlab.ico") if sys.platform == "win32" else None,
    version=VERSION_FILE if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ENCORLab")
