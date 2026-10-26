"""Lab library: browse and install lab packs and courses published in the project's GitHub repo
(labs/index.json) or from any https URL. Since 2.0.0 every lab comes from here (the app ships without labs).

Integrity: index entries carry a sha256 and size. A download is accepted only if both match, the URL is
https (plain http only for a library on this computer: localhost / 127.0.0.1 / ::1), and the file stays under
the size limit; it is then validated like any imported file before it is installed. Network access happens only
when the user opens the library or installs something (and once after an update to restore the labs an older
version bundled, see migrate.py).

Updates: a lab's `version:` (default 1) is published in the index; an installed copy with a lower version is
shown as "Update available". Installing records <lab>/.library.json (index URL, file, sha256, version)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable
from urllib.parse import urljoin, urlparse

from . import catalog, courses, objectives, packs, sizing, topics
from .schema import version_key

ORIGIN_FILE = ".library.json"

DEFAULT_INDEX = "https://raw.githubusercontent.com/Specops13/cml-lab-builder/main/library/index.json"
# labs/index.json (.encorlab / .encorcourse names) is kept for 2.0.x, which reads it under the old repo name
# (GitHub redirects that); packaging/build_library.py writes both folders from the same lab sources.
LEGACY_INDEX = "https://raw.githubusercontent.com/Specops13/encore-lab-app/main/labs/index.json"
MAX_INDEX_BYTES = 1024 * 1024
MAX_DOWNLOAD = courses.MAX_COURSE_BYTES
_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}\.(cmllab|cmlcourse|encorlab|encorcourse)$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")

Fetcher = Callable[[str, int], bytes]
_TRANSPORT = None   # tests inject an httpx.MockTransport here


class LibraryError(ValueError):
    pass


_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _check_url(url: str) -> str:
    u = urlparse(url)
    if u.scheme == "http" and u.hostname in _LOOPBACK:
        return url      # a library served from this computer (testing, offline mirrors)
    if u.scheme != "https" or not u.netloc:
        raise LibraryError(f"only https:// URLs are allowed (http only for localhost): {url}")
    return url


def default_url() -> str:
    """The configured library index URL (Settings > Library URL, CMLLAB_LIBRARY_URL), else the repo."""
    try:
        from .config import SettingsStore
        return SettingsStore().get().library_url or DEFAULT_INDEX
    except Exception:
        return DEFAULT_INDEX


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
                      headers={"User-Agent": "cml-lab-builder-library"}) as c:
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


def _load_index(raw: bytes) -> dict:
    try:
        d = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise LibraryError(f"library index is not valid JSON: {e}")
    if not isinstance(d, dict):
        raise LibraryError("library index has no 'items' list")
    return d


def parse_starter(raw: bytes) -> list[str]:
    st = _load_index(raw).get("starter")
    return [str(x) for x in st][:courses.MAX_LABS] if isinstance(st, list) else []


def _strs(v, n: int) -> list[str]:
    return [str(x)[:40] for x in v][:n] if isinstance(v, list) else []


def parse_index(raw: bytes) -> list[dict]:
    d = _load_index(raw)
    items = d.get("items")
    if not isinstance(items, list):
        raise LibraryError("library index has no 'items' list")
    out = []
    for it in items:
        if not (isinstance(it, dict) and _FILE_RE.match(str(it.get("file", "")))
                and _SHA_RE.match(str(it.get("sha256", ""))) and isinstance(it.get("size"), int)):
            continue   # skip malformed entries rather than failing the whole library
        kind = "course" if it["file"].endswith(courses.COURSE_EXTS) else "lab"
        out.append({"file": it["file"], "kind": kind, "id": str(it.get("id", "")), "title": str(it.get("title", it["file"])),
                    "description": str(it.get("description", "")), "sha256": it["sha256"], "size": it["size"],
                    "blueprint": [str(x) for x in it.get("blueprint", [])][:20],
                    "nodes": it.get("nodes") if isinstance(it.get("nodes"), int) else None,
                    "difficulty": it.get("difficulty") if isinstance(it.get("difficulty"), int) else None,
                    "ram_gb": float(it["ram_gb"]) if isinstance(it.get("ram_gb"), (int, float)) and 0 < it["ram_gb"] <= 4096 else None,
                    "type": it.get("type") if it.get("type") in ("challenge", "walkthrough") else None,
                    "version": str(it.get("version") or "1")[:20],
                    "labs": [str(x) for x in it.get("labs", [])][:courses.MAX_LABS],
                    # search fields (3.1.0+ indexes; older ones simply have none)
                    "domain": str(it.get("domain") or "")[:120], "track": str(it.get("track") or "")[:40],
                    "platforms": _strs(it.get("platforms"), 10), "node_types": _strs(it.get("node_types"), 20),
                    "topics": _strs(it.get("topics"), topics.MAX_TOPICS),
                    # exam objective tags (3.3.5+ indexes), well-formed ones only
                    "exams": [t for t in objectives.normalize(_strs(it.get("exams"), objectives.MAX_TAGS))
                              if objectives.split(t)]})
    # topic tags (3.2.0+ indexes): known ids only; labs without any (older or third-party indexes) get derived ones
    by_id = {}
    for o in out:
        if o["kind"] == "lab":
            o["topics"] = topics.for_lab(o)
            by_id[o["id"]] = o
    for o in out:
        if o["kind"] == "course":
            o["topics"] = topics.for_course(o, by_id)
    return out


def origin(lab_id: str) -> dict:
    """Where an installed lab came from (written by install_item), {} if unknown."""
    try:
        d = json.loads((catalog.user_labs_dir() / lab_id / ORIGIN_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _record_origin(lab_id: str, url: str, it: dict) -> None:
    d = catalog.user_labs_dir() / lab_id
    if d.is_dir():
        (d / ORIGIN_FILE).write_text(json.dumps({"index": url, "file": it["file"], "sha256": it["sha256"],
                                                 "version": it.get("version", "1")}, indent=1), encoding="utf-8")


_LAST: dict = {}     # the last index fetched in this process (the lab list shows "Update available" from it)


def last_index() -> dict:
    return _LAST


def index(url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch, *, heavy_gb: float = 16) -> dict:
    raw = fetch(_check_url(url), MAX_INDEX_BYTES)
    items = parse_index(raw)
    starter = parse_starter(raw)
    for it in items:
        it["ram_heavy"] = it["ram_gb"] is not None and it["ram_gb"] >= heavy_gb
    labs = catalog.entries()
    installed_courses = {c["id"] for c in courses.list_courses()}
    by_id = {it["id"]: it for it in items if it["kind"] == "lab"}
    for it in items:
        if it["kind"] == "course":
            it["installed"] = it["id"] in installed_courses
            it["missing"] = [lid for lid in it["labs"] if lid not in labs]
            it["installable"] = all(lid in by_id for lid in it["missing"])
        else:
            e = labs.get(it["id"])
            it["installed"] = e is not None
            it["builtin"] = e is not None and e.source == "builtin"
            it["starter"] = it["id"] in starter
            it["installed_version"] = e.lab.version if e else None
            it["update_available"] = bool(e and e.source == "user" and version_key(it["version"]) > e.lab.version_key)
    _LAST.clear()
    _LAST.update(url=url, updates=sorted(i["id"] for i in items if i.get("update_available")),
                 versions={i["id"]: i["version"] for i in items if i["kind"] == "lab"})
    used = [t for it in items for t in it.get("topics", [])]
    return {"url": url, "items": items, "starter": [s for s in starter if s in by_id],
            "updates": _LAST["updates"], "topics": topics.vocabulary(used),
            "exams": objectives.vocabulary([t for it in items for t in it.get("exams", [])])}


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


def _download(it: dict, url: str, fetch: Fetcher) -> bytes:
    data = fetch(_check_url(urljoin(url, it["file"])), min(MAX_DOWNLOAD, it["size"]))
    if len(data) != it["size"] or sha256(data) != it["sha256"]:
        raise LibraryError(f"integrity check failed for {it['file']}: size/sha256 do not match the library index")
    return data


def install_item(file: str, url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch,
                 node_limit: int = 20, overwrite: bool = False, _items: list[dict] | None = None) -> dict:
    """Install one library file. A course also installs the labs it lists that are not installed yet."""
    items = {i["file"]: i for i in (_items if _items is not None else parse_index(fetch(_check_url(url), MAX_INDEX_BYTES)))}
    it = items.get(file)
    if not it:
        raise LibraryError(f"{file!r} is not in the library index")
    data = _download(it, url, fetch)
    if it["kind"] == "course":
        return _install_course(data, file, url, fetch, items, node_limit, overwrite)
    d = install_bytes(file, data, node_limit=node_limit, overwrite=overwrite)
    _record_origin(d.get("lab_id") or it["id"], url, it)
    return d


def _install_course(data: bytes, file: str, url: str, fetch: Fetcher, items: dict, node_limit: int, overwrite: bool) -> dict:
    course, bundled = courses.read_course(data)
    by_id = {i["id"]: i for i in items.values() if i["kind"] == "lab"}
    need = courses.missing_labs(course, bundled)
    absent = [lid for lid in need if lid not in by_id]
    if absent:
        raise LibraryError(f"{file}: the library has no pack for {', '.join(absent)}")
    deps = [install_item(by_id[lid]["file"], url, fetch, node_limit, overwrite=False, _items=list(items.values()))["lab_id"]
            for lid in need]
    d = courses.install(data, node_limit=node_limit, overwrite=overwrite)
    d["from_library"] = deps
    d["installed"] = sorted(set(d.get("installed", [])) | set(deps))
    return d


def install_course_file(data: bytes, url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch,
                        node_limit: int = 20, overwrite: bool = False) -> dict:
    """A course imported from a local file: labs it lists that are neither bundled nor installed are installed
    from the library first. Offline, or with nothing missing, this is a plain courses.install."""
    course, bundled = courses.read_course(data)
    if not courses.missing_labs(course, bundled):
        return courses.install(data, node_limit=node_limit, overwrite=overwrite)
    try:
        items = {i["file"]: i for i in parse_index(fetch(_check_url(url), MAX_INDEX_BYTES))}
    except LibraryError:
        return courses.install(data, node_limit=node_limit, overwrite=overwrite)   # raises the "install first" error
    return _install_course(data, f"{course.id}{courses.COURSE_EXT}", url, fetch, items, node_limit, overwrite)


def install_many(ids: list[str] | None = None, *, starter: bool = False, updates: bool = False,
                 url: str = DEFAULT_INDEX, fetch: Fetcher = http_fetch, node_limit: int = 20) -> dict:
    """Install several library labs by id in one go (the starter set, a list, or every available update).
    Already-installed labs are skipped (updates: replaced). One failure does not stop the others."""
    raw = fetch(_check_url(url), MAX_INDEX_BYTES)
    items = parse_index(raw)
    by_id = {i["id"]: i for i in items if i["kind"] == "lab"}
    want = list(ids or [])
    if starter:
        want += parse_starter(raw)
    labs = catalog.entries()
    if updates:
        want += [lid for lid, it in by_id.items() if lid in labs and labs[lid].source == "user"
                 and version_key(it["version"]) > labs[lid].lab.version_key]
    done, skipped, failed = [], [], {}
    for lid in dict.fromkeys(want):
        if lid not in by_id:
            failed[lid] = "not in the library"
            continue
        if lid in labs and not updates:
            skipped.append(lid)
            continue
        try:
            install_item(by_id[lid]["file"], url, fetch, node_limit, overwrite=updates, _items=items)
            done.append(lid)
        except (LibraryError, packs.LabError) as e:
            failed[lid] = str(e)
    return {"ok": not failed, "installed": done, "skipped": skipped, "failed": failed}


def install_url(file_url: str, expected_sha256: str = "", fetch: Fetcher = http_fetch,
                node_limit: int = 20, overwrite: bool = False) -> dict:
    _check_url(file_url)
    name = urlparse(file_url).path.rsplit("/", 1)[-1] or "download"
    if not name.lower().endswith((*packs.PACK_EXTS, *courses.COURSE_EXTS, ".zip", ".yaml", ".yml")):
        raise LibraryError("the URL must point to a .cmllab, .cmlcourse (or .encorlab, .encorcourse), .zip or .yaml file")
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


def build_index(folder, base_items: list[dict] | None = None, lab_roots: list | None = None,
                topic_map: dict[str, list[str]] | None = None) -> dict:
    """Generate labs/index.json for a folder of .encorlab/.encorcourse files (used by packaging/build_library.py).
    lab_roots: folders with lab sources, to size courses that reference (not bundle) library labs."""
    from pathlib import Path
    folder = Path(folder)
    items = []
    for f in sorted(folder.iterdir()):
        if not _FILE_RE.match(f.name):
            continue
        data = f.read_bytes()
        it = {"file": f.name, "sha256": sha256(data), "size": len(data)}
        if f.name.endswith(courses.COURSE_EXTS):
            c, bundled = courses.read_course(data)
            it.update(kind="course", id=c.id, title=c.title, description=c.description, labs=c.labs)
            labs_by_id = {lid: e.lab for lid, e in catalog.entries().items()}
            for root in lab_roots or []:
                for d in catalog.lab_dirs(root):
                    labs_by_id.setdefault(d.name, catalog.load_lab_file(d / "lab.yaml"))
            for f2 in folder.iterdir():      # labs published next to the course
                if f2.name.endswith(packs.PACK_EXTS) and f2.stem not in labs_by_id:
                    labs_by_id[f2.stem] = packs.pack_lab(packs.read_upload(f2.name, f2.read_bytes()))
            for bp in bundled.values():
                bl = packs.pack_lab(bp)
                labs_by_id[bl.id] = bl
            rams = [sizing.estimate(labs_by_id[lid], labs_by_id[lid].platforms[0])["gb"]
                    for lid in c.labs if lid in labs_by_id]
            if rams:
                it["ram_gb"] = max(rams)
        else:
            pk = packs.read_upload(f.name, data)
            lab = packs.pack_lab(pk)
            it.update(kind="lab", id=lab.id, title=lab.title, version=lab.version, description=lab.summary,
                      blueprint=lab.blueprint, nodes=len(lab.nodes), difficulty=lab.difficulty, type=lab.type,
                      ram_gb=sizing.estimate(lab, lab.platforms[0])["gb"],
                      # for the library search: domain/track, image profiles and the CML node definitions used
                      domain=lab.domain, track=lab.track, platforms=list(lab.platforms),
                      node_types=sorted({d for p in lab.platforms for d in sizing.node_definitions(lab, p)}),
                      # exam objectives (3.3.5): lab-level first, then the ones only single steps cover
                      exams=objectives.lab_tags(lab))
        items.append(it)
    # topic tags (3.2.0): subject topics from topic_map (labsrc/library.yaml), else derived; then type and track
    by_id = {}
    for it in items:
        if it.get("kind") == "lab":
            it["topics"] = topics.for_lab({**it, "topics": (topic_map or {}).get(it["id"])})
            by_id[it["id"]] = it
    for it in items:
        if it.get("kind") == "course":
            it["topics"] = topics.for_course(it, by_id)
    return {"format": 1, "items": items}
