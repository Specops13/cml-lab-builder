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

# ---- runtime vs. app code -------------------------------------------------------------------------------------
# The encorlab package is NOT frozen into the PYZ archive. It ships as plain files in _internal/appcode/ (with a
# manifest) and is loaded by the boot loader (encorboot.py), which can also load a newer copy installed as a patch
# into the user data folder. Analysis still traces encorlab so every library it imports lands in the runtime.
sys.path.insert(0, ROOT)
import encorboot  # noqa: E402

APP_FILES = encorboot.iter_app_files(ROOT)
APP_MODULES = sorted({rel[:-3].replace("/", ".").removesuffix(".__init__") for rel, _ in APP_FILES if rel.endswith(".py")})
MANIFEST_DIR = os.path.join(ROOT, "build", "appcode-manifest")
os.makedirs(MANIFEST_DIR, exist_ok=True)
with open(os.path.join(MANIFEST_DIR, "manifest.json"), "w", encoding="utf-8") as fh:
    import json
    json.dump(encorboot.build_manifest(ROOT, VERSION), fh, indent=1, sort_keys=True)
datas = [(str(p), os.path.join("appcode", os.path.dirname(rel))) for rel, p in APP_FILES]
datas.append((os.path.join(MANIFEST_DIR, "manifest.json"), "appcode"))

# Future patches may use more of the standard library than today's code does, so the runtime carries nearly all of
# it (a few MB). New third-party dependencies always need a new runtime (RUNTIME_VERSION in encorboot.py).
_NO_STDLIB = {"tkinter", "_tkinter", "turtle", "turtledemo", "idlelib", "test", "lib2to3", "ensurepip", "venv",
              "pydoc_data", "distutils", "msilib", "antigravity", "this", "idle", "pydoc", "doctest", "tabnanny",
              "pdb", "profile", "cProfile", "pstats", "trace", "timeit", "unittest", "xxsubtype", "nturl2path",
              "curses", "_curses", "_curses_panel", "readline", "dbm", "_dbm", "_gdbm", "lzma", "_lzma", "nis",
              "ossaudiodev", "spwd", "crypt", "_crypt", "sndhdr", "audioop", "chunk", "aifc", "sunau", "wave",
              "mailcap", "nntplib", "telnetlib", "uu", "xdrlib", "pipes", "cgi", "cgitb", "imghdr", "msvcrt",
              "winreg", "winsound", "_winapi", "_overlapped", "nt", "posix", "pwd", "grp", "termios", "fcntl", "resource",
              "_posixsubprocess", "_posixshmem", "syslog", "_scproxy", "_osx_support", "_aix_support", "_android_support",
              "_ios_support", "__phello__", "__hello__", "_pyrepl", "_xxsubinterpreters", "_xxinterpchannels",
              "_xxinterpqueues", "_interpreters", "_interpchannels", "_interpqueues", "zipapp", "zipimport"}
_STDLIB = sorted(m for m in getattr(sys, "stdlib_module_names", ()) if m not in _NO_STDLIB and not m.startswith("_test"))
if sys.platform == "win32":
    _STDLIB += ["msvcrt", "winreg", "_winapi", "_overlapped", "nt"]
else:
    _STDLIB += ["posix", "pwd", "grp", "termios", "fcntl", "resource", "_posixsubprocess", "_posixshmem", "syslog"]
STDLIB_PACKAGES = ["asyncio", "collections", "concurrent", "email", "encodings", "html", "http", "importlib", "json",
                   "logging", "multiprocessing", "sqlite3", "urllib", "wsgiref", "xml", "xmlrpc", "zoneinfo", "ctypes"]
hiddenimports = (
    APP_MODULES + ["encorboot"] + _STDLIB
    + [m for pkg in STDLIB_PACKAGES for m in collect_submodules(pkg) if ".test" not in m and "idlelib" not in m]
    + collect_submodules("uvicorn")
    + collect_submodules("keyring.backends")
    + collect_submodules("fastapi") + collect_submodules("starlette")
    + collect_submodules("virl2_client") + collect_submodules("typer") + collect_submodules("yaml")
    + ["multipart", "python_multipart", "email_validator"]
)
for dist in ("virl2_client", "keyring", "fastapi", "pydantic", "uvicorn", "typer", "paramiko"):
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
# drop the app code from the frozen archive: it is loaded from appcode/ (or an installed patch) at start
a.pure = [e for e in a.pure if not (e[0] == "encorlab" or e[0].startswith("encorlab."))]
a.datas = [e for e in a.datas if not os.path.normpath(e[0]).startswith(os.path.join("encorlab", ""))]
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
