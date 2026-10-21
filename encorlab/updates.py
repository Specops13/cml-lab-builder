"""Update check against GitHub Releases, plus app-code patches for the packaged app.

check() sends one anonymous GET to the GitHub Releases API. In the packaged app the background updater
(autoupdate.py) calls it every few hours (Settings > Updates), downloads and verifies a newer release's patch and
asks before installing it. Nothing is installed without the user's "Update now" / "Install update"."""
from __future__ import annotations

import json
import os
import re

from . import __version__, library

REPO = "Specops13/cml-lab-builder"   # renamed from encore-lab-app in 2.1.0 (GitHub redirects the old name)
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
_VER = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?")


def parse_version(v: str) -> tuple[int, int, int] | None:
    m = _VER.match(str(v).strip())
    return (int(m[1]), int(m[2]), int(m[3] or 0)) if m else None


def release_url() -> str:
    """The Releases API URL. ENCOR_UPDATE_URL overrides it (smoke tests against a local fake release; an http URL is
    only accepted for 127.0.0.1 / localhost)."""
    u = os.environ.get("ENCOR_UPDATE_URL", "").strip()
    return u if u and allowed_url(u) else LATEST_URL


def asset_prefixes() -> tuple[str, ...]:
    """Download URLs accepted for release assets: github.com, or the origin of the ENCOR_UPDATE_URL override."""
    u = release_url()
    if u == LATEST_URL:
        return ("https://github.com/",)
    from urllib.parse import urlsplit
    p = urlsplit(u)
    return ("https://github.com/", f"{p.scheme}://{p.netloc}/")


def allowed_url(url: str) -> bool:
    """https anywhere; plain http only to the loopback interface (local test servers)."""
    from urllib.parse import urlsplit
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    return p.scheme == "https" and bool(p.hostname) or (p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost"))


class HTTPStatusError(library.LibraryError):
    def __init__(self, status: int, url: str, headers: dict | None = None):
        super().__init__(f"HTTP {status} for {url}")
        self.status, self.headers = status, dict(headers or {})


def http_get(url: str, limit: int, etag: str | None = None, timeout: float = 20) -> tuple[int, bytes, dict]:
    """GET with a size cap, an optional If-None-Match (ETag) and the URL rules of allowed_url() applied to every
    request, redirects included. Returns (status, body, headers): 200 with the body, or 304 with b"".
    Raises HTTPStatusError for other statuses and library.LibraryError for network errors."""
    import httpx

    def guard(request):
        if not allowed_url(str(request.url)):
            raise library.LibraryError(f"refusing to fetch {request.url} (https only)")
    if not allowed_url(url):
        raise library.LibraryError(f"refusing to fetch {url} (https only)")
    headers = {"User-Agent": f"encorlab/{__version__}", "Accept": "application/vnd.github+json, */*"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers,
                          event_hooks={"request": [guard]}) as c:
            with c.stream("GET", url) as r:
                hdrs = {k.lower(): v for k, v in r.headers.items()}
                if r.status_code == 304:
                    return 304, b"", hdrs
                if r.status_code != 200:
                    raise HTTPStatusError(r.status_code, url, hdrs)
                if int(r.headers.get("content-length") or 0) > limit:
                    raise library.LibraryError(f"{url} is larger than {limit // 1024} KB")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > limit:
                        raise library.LibraryError(f"{url} is larger than {limit // 1024} KB")
                return 200, bytes(buf), hdrs
    except httpx.HTTPError as e:
        raise library.LibraryError(f"network error fetching {url}: {e.__class__.__name__}: {e}")


def fetch(url: str, limit: int) -> bytes:
    """Plain GET (no ETag) with the update URL rules; the default fetcher of check() / install()."""
    return http_get(url, limit)[1]


def check(current: str = __version__, fetch=library.http_fetch, url: str = LATEST_URL) -> dict:
    """Compare the running version with the latest published release. Raises library.LibraryError on failure."""
    raw = fetch(url, 512 * 1024)
    return parse_release(raw, current)


def parse_release(raw: bytes, current: str = __version__) -> dict:
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise library.LibraryError("GitHub returned an invalid response")
    if not isinstance(d, dict):
        raise library.LibraryError("GitHub returned an invalid response")
    tag = str(d.get("tag_name") or "")
    latest = parse_version(tag)
    if not latest:
        raise library.LibraryError(f"latest release has no version tag ({tag!r})")
    cur = parse_version(current)
    html = str(d.get("html_url") or RELEASES_PAGE)
    if not html.startswith("https://github.com/"):
        html = RELEASES_PAGE
    ok = asset_prefixes()
    assets = [{"name": str(a.get("name", "")), "size": a.get("size"), "url": str(a.get("browser_download_url", ""))}
              for a in (d.get("assets") or []) if isinstance(a, dict)
              and str(a.get("browser_download_url", "")).startswith(ok)]
    from . import install as _inst
    kind = _inst.install_type()
    dl = _inst.full_download(assets, ".".join(map(str, latest)), kind)
    return {"current": current, "latest": ".".join(map(str, latest)), "tag": tag, "install_type": kind, "download": dl,
            "update_available": bool(cur and latest > cur), "newer_than_latest": bool(cur and cur > latest),
            "url": html, "name": str(d.get("name") or tag), "published_at": d.get("published_at"),
            "notes": str(d.get("body") or "")[:4000], "assets": assets}


# ====================================================================== patch updates (packaged app only)
# A release can carry a small app-code patch, encorlab-patch-<version>.zip, next to the full downloads. The patch
# contains manifest.json (app_version, min_runtime, sha256 of every file) and the encorlab/ package. "Install update"
# downloads SHA256SUMS.txt and the patch from the GitHub release, checks the patch's sha256 against SHA256SUMS,
# checks every file against the manifest, and extracts it to <data dir>/app/<version>/. The boot loader
# (encorboot.py, part of the runtime) uses it from the next start on. If the patch needs a newer runtime
# (min_runtime), nothing is installed and the user is told to download the full release.
import io
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

PATCH_PREFIX = "encorlab-patch-"
SUMS_NAMES = ("SHA256SUMS.txt", "SHA256SUMS")
MAX_PATCH_BYTES = 30 * 1024 * 1024
MAX_UNPACKED_BYTES = 120 * 1024 * 1024
MAX_FILES = 3000


class UpdateError(ValueError):
    pass


class RuntimeTooOld(UpdateError):
    def __init__(self, needed: int, have: int):
        super().__init__(f"this update needs runtime {needed} (you have runtime {have}): download the full release")
        self.needed, self.have = needed, have


def patch_name(version: str) -> str:
    return f"{PATCH_PREFIX}{version}.zip"


def _boot():
    """The boot loader module, or None when it is unavailable (should not happen: it ships with the app)."""
    try:
        import encorboot
        return encorboot
    except ImportError:
        return None


def patchable() -> tuple[bool, str]:
    b = _boot()
    if b is None:
        return False, "the boot loader (encorboot) is missing"
    if not b.frozen():
        return False, "running from source: update with git pull (or download a new source zip) instead"
    if b.ACTIVE is None:
        return False, "the app was not started through the boot loader"
    return True, ""


def status() -> dict:
    """What the Updates panel shows: running app code, runtime, installed patch, rollback and restart state."""
    b = _boot()
    ok, why = patchable()
    from . import install as _inst
    out = {"version": __version__, "patchable": ok, "reason": why, "runtime": getattr(b, "RUNTIME_VERSION", None),
           "install_type": _inst.install_type(), "app_dir": str(_inst.app_dir() or ""),
           "active": None, "bundled_version": None, "installed": None, "previous": None, "pending": False,
           "failed": None, "can_rollback": False, "next_start": None, "restart_needed": False, "can_restart": False}
    if b is None:
        return out
    if b.ACTIVE is not None:
        out["active"] = {"version": b.ACTIVE.version, "source": b.ACTIVE.source}
    bundled = b.candidate_at(b.bundled_dir(), "bundled")
    out["bundled_version"] = bundled.version if bundled else None
    if ok:
        st = b.load_state()
        nxt = b.next_start()
        out.update(installed=st.get("current"), previous=st.get("previous"), pending=bool(st.get("pending")),
                   failed=st.get("failed") or None, can_rollback=bool(st.get("current")),
                   next_start={"version": nxt.version, "source": nxt.source} if nxt else None)
        out["restart_needed"] = bool(nxt and b.ACTIVE and (nxt.version, nxt.source) != (b.ACTIVE.version, b.ACTIVE.source))
        try:
            from . import launcher
            out["can_restart"] = launcher.can_restart()
        except Exception:
            pass
    return out


def parse_sums(text: str) -> dict[str, str]:
    """`sha256sum` output: '<hex>  <name>' (or '<hex> *<name>') per line."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(\S.*?)\s*$", line)
        if m:
            out[m[2].strip()] = m[1].lower()
    return out


def _safe_member(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or ":" in name.split("/")[0]:
        return False
    parts = PurePosixPath(name).parts
    return ".." not in parts and "" not in parts


def verify_patch(data: bytes, expected_version: str | None = None, runtime: int | None = None,
                 package: str = "encorlab") -> dict:
    """Validate a patch zip; returns its manifest. Raises UpdateError / RuntimeTooOld."""
    if len(data) > MAX_PATCH_BYTES:
        raise UpdateError("patch is too large")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise UpdateError("patch is not a valid zip file")
    with z:
        infos = z.infolist()
        if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise UpdateError("patch is too large when unpacked")
        names = [i.filename for i in infos if not i.is_dir()]
        if "manifest.json" not in names:
            raise UpdateError("patch has no manifest.json")
        try:
            m = json.loads(z.read("manifest.json").decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise UpdateError("patch manifest is not valid JSON")
        if not isinstance(m, dict) or m.get("format") != 1 or m.get("package") != package:
            raise UpdateError("patch manifest has an unknown format")
        ver = str(m.get("app_version") or "")
        if not parse_version(ver):
            raise UpdateError("patch manifest has no valid app_version")
        if expected_version and ver != expected_version:
            raise UpdateError(f"patch is for version {ver}, expected {expected_version}")
        try:
            need = int(m.get("min_runtime"))
        except (TypeError, ValueError):
            raise UpdateError("patch manifest has no valid min_runtime")
        if runtime is not None and need > runtime:
            raise RuntimeTooOld(need, runtime)
        files = m.get("files")
        if not isinstance(files, dict) or f"{package}/__init__.py" not in files:
            raise UpdateError(f"patch manifest does not list {package}/__init__.py")
        members = set(names) - {"manifest.json"}
        for n in members | set(files):
            if not _safe_member(n) or not n.startswith(package + "/"):
                raise UpdateError(f"patch contains a file outside {package}/: {n!r}")
        if members != set(files):
            extra, missing = sorted(members - set(files))[:3], sorted(set(files) - members)[:3]
            raise UpdateError(f"patch files do not match its manifest (extra {extra}, missing {missing})")
        for n in sorted(members):
            if library.sha256(z.read(n)) != str(files[n]).lower():
                raise UpdateError(f"checksum mismatch for {n}")
        init = z.read(f"{package}/__init__.py").decode("utf-8", "replace")
        if f'__version__ = "{ver}"' not in init:
            raise UpdateError(f"{package}/__init__.py does not declare version {ver}")
    return m


def install_bytes(data: bytes, expected_version: str | None = None, package: str = "encorlab") -> dict:
    """Verify and extract a patch into <data dir>/app/<version>/ and stage it for the next start."""
    b = _boot()
    if b is None:
        raise UpdateError("the boot loader (encorboot) is missing")
    m = verify_patch(data, expected_version, b.RUNTIME_VERSION, package)
    ver = m["app_version"]
    root = b.app_root()
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".{ver}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for n in m["files"]:
                dest = tmp / n
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(z.read(n))
        (tmp / "manifest.json").write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
        _precompile(tmp)
        target = root / ver
        if b.ACTIVE is not None and b.ACTIVE.source == "installed" and b.ACTIVE.version == ver:
            raise UpdateError(f"version {ver} is the one running now")
        if target.exists():
            shutil.rmtree(target)
        os.replace(tmp, target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    b.stage(ver, package)
    return {"status": "installed", "version": ver, "min_runtime": m["min_runtime"], "restart_required": True,
            "path": str(root / ver)}


def _precompile(d: Path) -> None:
    """Byte-compile once at install time so the first start is fast (hash-checked, so file times don't matter)."""
    try:
        import compileall
        import py_compile
        compileall.compile_dir(str(d), quiet=1, workers=1,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
    except Exception:
        pass


def _dl_url(info: dict) -> str:
    """Full download for this install type (the .deb for deb installs), else the release page."""
    return (info.get("download") or {}).get("url") or info["url"]


def install(current: str = __version__, fetch=fetch, url: str | None = None) -> dict:
    """Check GitHub, download the patch for the latest release, verify it and install it.
    Returns {"status": "installed" | "up_to_date" | "full_download", ...}."""
    ok, why = patchable()
    if not ok:
        raise UpdateError(f"Install update is not available: {why}")
    info = check(current, fetch=fetch, url=url or release_url())
    if not info["update_available"]:
        return {"status": "up_to_date", "current": current, "latest": info["latest"], "url": info["url"]}
    by_name = {a["name"]: a for a in info["assets"]}
    pname = patch_name(info["latest"])
    patch = by_name.get(pname)
    sums = next((by_name[n] for n in SUMS_NAMES if n in by_name), None)
    if not patch:
        return {"status": "full_download", "latest": info["latest"], "url": _dl_url(info), "page": info["url"],
                "download": info.get("download"), "reason": f"release {info['tag']} has no app patch ({pname})"}
    if not sums:
        raise UpdateError(f"release {info['tag']} has no SHA256SUMS.txt, so the patch cannot be verified")
    try:
        expected = parse_sums(fetch(sums["url"], 1024 * 1024).decode("utf-8", "replace")).get(pname)
    except library.LibraryError as e:
        raise UpdateError(f"could not download SHA256SUMS: {e}")
    if not expected:
        raise UpdateError(f"SHA256SUMS of {info['tag']} has no entry for {pname}")
    try:
        data = fetch(patch["url"], MAX_PATCH_BYTES)
    except library.LibraryError as e:
        raise UpdateError(f"could not download the patch: {e}")
    got = library.sha256(data)
    if got != expected:
        raise UpdateError(f"patch checksum mismatch (got {got[:12]}…, SHA256SUMS says {expected[:12]}…); nothing was installed")
    try:
        res = install_bytes(data, expected_version=info["latest"])
    except RuntimeTooOld as e:
        return {"status": "full_download", "latest": info["latest"], "url": _dl_url(info), "page": info["url"],
                "download": info.get("download"), "reason": str(e), "needed_runtime": e.needed, "runtime": e.have}
    res.update({"size": len(data), "sha256": got, "url": info["url"], "previous": current})
    return res


def install_file(path, sha256: str | None = None) -> dict:
    """Install a patch zip from disk (offline installs, smoke tests). Same checks as install(), minus SHA256SUMS
    unless the expected sha256 is given."""
    ok, why = patchable()
    if not ok:
        raise UpdateError(f"Install update is not available: {why}")
    data = Path(path).read_bytes()
    got = library.sha256(data)
    if sha256 and got != sha256.strip().lower():
        raise UpdateError(f"checksum mismatch for {Path(path).name}: {got}")
    try:
        res = install_bytes(data)
    except RuntimeTooOld as e:
        return {"status": "full_download", "reason": str(e), "url": RELEASES_PAGE, "needed_runtime": e.needed,
                "runtime": e.have}
    res.update({"size": len(data), "sha256": got})
    return res


def rollback() -> dict:
    ok, why = patchable()
    if not ok:
        raise UpdateError(f"Roll back is not available: {why}")
    b = _boot()
    try:
        r = b.rollback()
    except ValueError as e:
        raise UpdateError(str(e))
    return {"status": "rolled_back", "next": r["next"], "restart_required": True}
