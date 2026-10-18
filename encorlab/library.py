"""Lab library: browse and install lab packs and courses published in the project's GitHub repo
(labs/index.json) or from any https URL.

Integrity: index entries carry a sha256 and size. A download is accepted only if both match, the URL is
https, and the file stays under the size limit; it is then validated like any imported file before it is
installed. Network access happens only when the user opens the library or installs something."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable
from urllib.parse import urljoin, urlparse

from . import catalog, courses, packs

DEFAULT_INDEX = "https://raw.githubusercontent.com/Specops13/encore-lab-app/main/labs/index.json"
MAX_INDEX_BYTES = 1024 * 1024
MAX_DOWNLOAD = courses.MAX_COURSE_BYTES
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(encorlab|encorcourse)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

Fetcher = Callable[[str, int], bytes]
_TRANSPORT = None   # tests inject an httpx.MockTransport here


class LibraryError(ValueError):
    pass


def _check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme != "https" or not u.netloc:
        raise LibraryError(f"only https:// URLs are allowed: {url}")
    return url


def http_fetch(url: str, limit: int) -> bytes:
    """GET with a size cap (streamed) and https enforced on every redirect."""
    import httpx
    _check_url(url)
    try:
        return _get(httpx, url, limit)
    except httpx.HTTPError as e:
        raise LibraryError(f"network error fetching {url}: {e.__class__.__name__}: {e}")


def _get(httpx, url: str, limit: int) -> bytes:
    with httpx.Client(timeout=20, follow_redirects=True, transport=_TRANSPORT,
                      headers={"User-Agent": "encorlab-library"}) as c:
        with c.stream("GET", url) as r:
            for h in r.history + [r]:
                _check_url(str(h.url))
            if r.status_code != 200:
                raise LibraryError(f"download failed: HTTP {r.status_code} for {url}")
            if int(r.headers.get("content-length") or 0) > limit:
                raise LibraryError(f"file is larger than {limit // 1024 // 1024} MB")
            buf = bytearray()
            for chunk in r.iter_bytes():
                buf += chunk
                if len(buf) > limit:
                    raise LibraryError(f"file is larger than {limit // 1024 // 1024} MB")
            return bytes(buf)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_index(raw: bytes) -> list[dict]:
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise LibraryError(f"library index is not valid JSON: {e}")
    items = d.get("items") if isinstance(d, dict) else None
    if not isinstance(items, list):
        raise LibraryError("library index has no 'items' list")
    out = []
    for it in items:
        if not (isinstance(it, dict) and _FILE_RE.match(str(it.get("file", "")))
                and _SHA_RE.match(str(it.get("sha256", ""))) and isinstance(it.get("size"), int)):
            continue   # skip malformed entries rather than failing the whole library
        kind = "course" if it["file"].endswith(courses.COURSE_EXT) else "lab"
        out.append({"file": it["file"], "kind": kind, "id": str(it.get("id", "")), "title": str(it.get("title", it["file"])),
                    "description": str(it.get("description", "")), "sha256": it["sha256"], "size": it["size"],
                    "blueprint": [str(x) for x in it.get("blueprint", [])][:20],
                    "nodes": it.get("nodes") if isinstance(it.get("nodes"), int) else None,
                    "difficulty": it.get("difficulty") if isinstance(it.get("difficulty"), int) else None,
                    "labs": [str(x) for x in it.get("labs", [])][:courses.MAX_LABS]})
    return out


def index(url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch) -> dict:
    items = parse_index(fetch(_check_url(url), MAX_INDEX_BYTES))
    labs = catalog.entries()
    installed_courses = {c["id"] for c in courses.list_courses()}
    for it in items:
        if it["kind"] == "course":
            it["installed"] = it["id"] in installed_courses
        else:
            e = labs.get(it["id"])
            it["installed"] = e is not None
            it["builtin"] = e is not None and e.source == "builtin"
    return {"url": url, "items": items}


def install_bytes(name: str, data: bytes, node_limit: int = 20, overwrite: bool = False) -> dict:
    """Install a downloaded/uploaded lab pack or course. Raises packs.LabError on validation problems."""
    if courses.is_course(name, data):
        return courses.install(data, node_limit=node_limit, overwrite=overwrite)
    pk = packs.read_upload(name, data)
    rep = packs.install(pk, node_limit=node_limit, overwrite=overwrite)
    if not rep.ok:
        raise packs.LabError(rep.errors, rep.warnings)
    d = rep.to_dict()
    d["kind"] = "lab"
    d["warnings"] = pk.warnings + rep.warnings
    return d


def install_item(file: str, url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch,
                 node_limit: int = 20, overwrite: bool = False) -> dict:
    items = {i["file"]: i for i in parse_index(fetch(_check_url(url), MAX_INDEX_BYTES))}
    it = items.get(file)
    if not it:
        raise LibraryError(f"{file!r} is not in the library index")
    data = fetch(_check_url(urljoin(url, file)), min(MAX_DOWNLOAD, it["size"]))
    if len(data) != it["size"] or sha256(data) != it["sha256"]:
        raise LibraryError(f"integrity check failed for {file}: size/sha256 do not match the library index")
    return install_bytes(file, data, node_limit=node_limit, overwrite=overwrite)


def install_url(file_url: str, expected_sha256: str = "", fetch: Fetcher = http_fetch,
                node_limit: int = 20, overwrite: bool = False) -> dict:
    _check_url(file_url)
    name = urlparse(file_url).path.rsplit("/", 1)[-1] or "download"
    if not name.lower().endswith((packs.PACK_EXT, courses.COURSE_EXT, ".zip", ".yaml", ".yml")):
        raise LibraryError("the URL must point to a .encorlab, .encorcourse, .zip or .yaml file")
    exp = expected_sha256.strip().lower()
    if exp and not _SHA_RE.match(exp):
        raise LibraryError("sha256 must be 64 hex characters")
    data = fetch(file_url, MAX_DOWNLOAD)
    got = sha256(data)
    if exp and got != exp:
        raise LibraryError(f"integrity check failed: sha256 is {got}, expected {exp}")
    d = install_bytes(name, data, node_limit=node_limit, overwrite=overwrite)
    d["sha256"] = got
    d["verified"] = bool(exp)
    return d


def build_index(folder, base_items: list[dict] | None = None) -> dict:
    """Generate labs/index.json for a folder of .encorlab/.encorcourse files (used by packaging/build_library.py)."""
    from pathlib import Path
    folder = Path(folder)
    items = []
    for f in sorted(folder.iterdir()):
        if not _FILE_RE.match(f.name):
            continue
        data = f.read_bytes()
        it = {"file": f.name, "sha256": sha256(data), "size": len(data)}
        if f.name.endswith(courses.COURSE_EXT):
            c, bundled = courses.read_course(data)
            it.update(kind="course", id=c.id, title=c.title, description=c.description, labs=c.labs)
        else:
            pk = packs.read_upload(f.name, data)
            lab, _ = packs.parse_lab_text(pk.lab_yaml)
            it.update(kind="lab", id=lab.id, title=lab.title, description=lab.summary, blueprint=lab.blueprint,
                      nodes=len(lab.nodes), difficulty=lab.difficulty)
        items.append(it)
    return {"format": 1, "items": items}
