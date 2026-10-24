"""Resource pre-check before a build (3.3.0): does the lab fit on the CML server right now?

Reads, with the user's own CML login (virl2_client):
  - system stats (GET /system_stats): total / free memory of all compute hosts,
  - licensing (GET /licensing): licensed node count and nodes in use (when the user may read it),
  - the labs (all users' labs for an admin, else the user's own) and their running nodes with each node's RAM
    (the node's `ram` setting, else the CML 2.9 node-definition default from sizing.py).

Verdict for a lab that needs N GB (sizing.estimate, or the author's ram_gb):
  available = min(free memory, total memory - RAM of all running nodes)      (+ the RAM this lab already uses)
  fits      available - N >= headroom       (Settings > Resource check headroom, default 4 GB)
  tight     0 <= available - N < headroom   (it probably starts, but the server is nearly full)
  no-fit    available - N < 0, or the licensed node count / the node limit would be exceeded
  unknown   the memory could not be read (not an admin, older CML, network error): build anyway or cancel.
Memory and node licenses are judged separately (3.3.1) and the verdict says which one failed; when the license
cannot be read the node part is "can't tell", never "won't fit".
Everything is best effort: a failing call never blocks a build, it only makes the verdict "unknown"."""
from __future__ import annotations

import threading
import time

from . import sizing
from .cml import ACTIVE, LEGACY_PREFIXES, UNCOUNTED

DEFAULT_HEADROOM_GB = 4.0
CACHE_SECONDS = 30.0
GIB = 1024 ** 3


def _gb(value, unit_hint: str = "auto") -> float | None:
    """Memory from the API in GB. system_stats reports bytes; node `ram` is MiB (some client versions say bytes)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return 0.0
    if unit_hint == "bytes":
        return v / GIB
    if unit_hint == "mib" and v < 4 * 1024 * 1024:     # < 4 TiB in MiB: MiB
        return v / 1024
    if v >= 64 * 1024 * 1024:                          # bytes
        return v / GIB
    return v / 1024                                   # MiB


def _host_memory(mem: dict) -> tuple[float | None, float | None]:
    """(total_gb, free_gb) of one memory block of GET /system_stats.

    CML reports bytes. "free" is the kernel's MemFree, which leaves out the page cache and buffers (on a CML host
    that read a few qcow2 images, tens of GB): that memory is reclaimed as soon as a node starts, so the usable free
    memory is total - used when "used" is there (3.3.1; 3.3.0 took MemFree and could call a roomy server full).
    A server reporting less than 2 GB in "bytes" is really reporting KiB (no CML host has under 8 GB)."""
    if not isinstance(mem, dict) or mem.get("total") is None:
        return None, None
    try:
        raw = {k: float(mem[k]) for k in ("total", "free", "used") if mem.get(k) is not None}
    except (TypeError, ValueError):
        return None, None
    scale = GIB
    if raw["total"] < 2 * GIB:                         # not bytes: KiB (or MiB on something very odd)
        scale = 1024 ** 2 if raw["total"] >= 2 * 1024 ** 2 else 1024
    total = raw["total"] / scale
    free = raw["free"] / scale if "free" in raw else None
    if "used" in raw:
        usable = max(0.0, total - raw["used"] / scale)
        free = usable if free is None else max(free, usable)
    return total, free


def _memory(stats: dict) -> tuple[float | None, float | None]:
    """(total_gb, free_gb) summed over the compute hosts."""
    if not isinstance(stats, dict):
        return None, None
    mem = (stats.get("all") or {}).get("memory") if isinstance(stats.get("all"), dict) else None
    if not isinstance(mem, dict):
        total = free = 0.0
        found = False
        for c in (stats.get("computes") or {}).values():
            t, f = _host_memory(((c or {}).get("stats") or {}).get("memory") or {})
            if t is not None:
                found = True
                total += t
                free += f or 0.0
        return (round(total, 1), round(free, 1)) if found else (None, None)
    total, free = _host_memory(mem)
    return (round(total, 1) if total is not None else None, round(free, 1) if free is not None else None)


# ---------------------------------------------------------------- node licenses (3.3.1)
# GET /licensing lists Smart Licensing *features*, not nodes. In CML 2.9 the base product license is one feature with
# in_use 1 / max 1 ("CML - Enterprise License ... with 20 nodes capacity included"); extra capacity is the
# "CML - Expansion Nodes" feature (id ...CML_NODE_COUNT...), whose in_use is the expansion count the admin chose
# (max is only the most that may be chosen, 300). 3.3.0 summed every feature's max/in_use and so showed
# "1 of 1 licensed nodes in use" and "won't fit" for every lab. The node capacity is the base's included nodes plus
# the expansion count; how many nodes use a license right now comes from GET /diagnostics/licensing
# ({"quota", "started", ...}) or, failing that, from counting the running nodes of all labs (minus unmanaged switches
# and external connectors, which never use a license).
# 3.3.2: "user_quota" / "user_started" of /diagnostics/licensing are NOT a per-user node limit (3.3.1 read them as
# one): on a CML Personal server user_quota is 1 with 0 node licenses in use, i.e. a count of users, so every lab got
# "your resource pool allows 1 nodes". A per-user node limit only exists when the login is assigned a CML resource
# pool whose resolved limit has a number in "licenses" (GET /users/{id} -> resource_pool, then
# GET /resource_pool_usage/{pool}); no pool, or licenses null, means unlimited.
INCLUDED_NODES = {"enterprise": 20, "personal40": 40, "personal_plus": 40, "personalplus": 40, "personal": 20, "free": 5}


def _int(v) -> int | None:
    try:
        return int(v) if v is not None and not isinstance(v, bool) else None
    except (TypeError, ValueError):
        return None


def _license_capacity(status: dict) -> tuple[int | None, str, list]:
    """(licensed node capacity or None, product name, features as shown) from GET /licensing."""
    import re
    if not isinstance(status, dict):
        return None, "", []
    product = str(((status.get("product_license") or {}).get("active")) or "")
    feats = [f for f in (status.get("features") or []) if isinstance(f, dict)]
    shown = [{"name": str(f.get("name") or f.get("id") or "?")[:80], "in_use": _int(f.get("in_use")),
              "max": _int(f.get("max"))} for f in feats]
    included = expansion = None
    for f in feats:
        ident = f"{f.get('id') or ''} {f.get('name') or ''}".lower()
        if "node_count" in ident or "expansion" in ident:
            expansion = (expansion or 0) + (_int(f.get("in_use")) or 0)
            continue
        m = re.search(r"(\d+)\s*(?:cisco\s+)?nodes?\b", str(f.get("description") or "") + " " + str(f.get("name") or ""),
                      re.I)
        if m and (_int(f.get("in_use")) or 0) > 0:
            included = max(included or 0, int(m.group(1)))
    if included is None and product:
        key = product.lower().replace("cml_", "").replace("-", "_")
        for k in sorted(INCLUDED_NODES, key=len, reverse=True):
            if key.startswith(k):
                included = INCLUDED_NODES[k]
                break
    if included is None:
        return None, product, shown
    return included + (expansion or 0), product, shown


def _license(status, diag, running_counted: int | None) -> dict | None:
    """Node-license view for the verdict, or None when nothing could be read (non-admin login).

    {"max", "in_use", "known", "source", "product", "features", "note"}; known is False
    when either number is missing: the verdict then says "can't tell" for nodes instead of "won't fit"."""
    capacity, product, shown = _license_capacity(status) if isinstance(status, dict) else (None, "", [])
    out = {"max": capacity, "in_use": None, "known": False, "source": "licensing", "product": product,
           "features": shown, "note": ""}
    d = diag.get("licensing", diag) if isinstance(diag, dict) else None
    if isinstance(d, dict) and "started" in d and "error" not in d:
        started, quota = _int(d.get("started")), _int(d.get("quota"))
        if started is not None:
            out.update(in_use=started, source="diagnostics")
            if quota is not None and quota > 0:
                out["max"] = quota
    if out["in_use"] is None and running_counted is not None and out["max"] is not None:
        out.update(in_use=running_counted, source="licensing+labs")
    if out["max"] is None and out["in_use"] is None and not shown:
        return None
    out["known"] = out["max"] is not None and out["in_use"] is not None
    if not out["known"]:
        out["note"] = ("the licensed node count could not be read" if out["max"] is None
                       else "the nodes in use could not be counted")
    return out


def _user_pool(client) -> dict:
    """The login's CML resource pool and its node-license limit (read-only GETs).

    {"assigned": True/False/None (None = could not tell), "id", "label", "max", "in_use", "error", "raw_usage"}.
    "max" is only set when CML reports a whole number of node licenses for the pool (null = unlimited)."""
    out = {"assigned": None, "id": None, "label": "", "max": None, "in_use": None, "error": "", "raw_usage": None}
    try:
        um = client.user_management
        user = um.get_user(um.user_id(client.username))
    except Exception as e:
        out["error"] = f"user: {_why(e)}"
        return out
    pid = user.get("resource_pool") if isinstance(user, dict) else None
    if not pid:
        out["assigned"] = False
        return out
    out.update(assigned=True, id=str(pid))
    try:
        usage = client._session.get(f"resource_pool_usage/{pid}").json()
    except Exception as e:
        out["error"] = f"resource pool usage: {_why(e)}"
        return out
    out["raw_usage"] = usage
    if isinstance(usage, dict):
        out["label"] = str(usage.get("label") or "")[:80]
        lim = (usage.get("limit") or {}).get("licenses") if isinstance(usage.get("limit"), dict) else None
        used = (usage.get("usage") or {}).get("licenses") if isinstance(usage.get("usage"), dict) else None
        lim, used = _int(lim), _int(used)
        if lim is not None and lim > 0:
            out["max"], out["in_use"] = lim, used
    return out


_SECRET_KEYS = ("password", "passwd", "secret", "token", "key", "serial", "udi", "uuid", "account", "hostname",
                "email", "proxy", "ssms", "fullname", "username", "cookie", "auth_header", "sn")
_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def redact_tree(v, _key: str = ""):
    """Copy of a JSON value with secrets, serials, ids, host names, accounts and IP addresses removed."""
    import re
    from .config import redact
    k = _key.lower()
    if k and k not in ("key_id",) and any(s == k or s in k.split("_") or k.endswith(s) for s in _SECRET_KEYS) \
            and v not in (None, "", [], {}):
        return "***"
    if isinstance(v, dict):
        out, n = {}, 0
        for kk, vv in v.items():
            name = str(kk)
            if re.fullmatch(_UUID, name):
                n += 1
                name = f"<id-{n}>"
            out[name] = redact_tree(vv, str(kk))
        return out
    if isinstance(v, (list, tuple)):
        return [redact_tree(x, _key) for x in v]
    if isinstance(v, str):
        s = re.sub(_UUID, "<id>", redact(v))
        s = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<ip>", s)
        return re.sub(r"https?://[^\s\"']+", "<url>", s)
    return v


def debug_dump(client, prefixes=("CML-",)) -> dict:
    """What the resource check read from CML (raw, read-only GETs) and what it made of it, redacted for sharing:
    licensing status, licensing diagnostics, system stats, the login's resource pool and the computed view."""
    from . import __version__
    raw: dict = {}

    def grab(name, fn):
        try:
            raw[name] = fn()
        except Exception as e:
            raw[name] = {"error": _why(e)}
    grab("licensing", lambda: client.licensing.status())

    def _diag():
        from virl2_client.virl2_client import DiagnosticsCategory
        return client.get_diagnostics(DiagnosticsCategory.LICENSING)
    grab("diagnostics_licensing", _diag)
    grab("system_stats", client.get_system_stats)
    grab("resource_pool", lambda: _user_pool(client))
    try:
        user = client.user_management.get_user(client.user_management.user_id(client.username))
        raw["user"] = {"admin": user.get("admin"), "resource_pool": user.get("resource_pool")}
    except Exception as e:
        raw["user"] = {"error": _why(e)}
    try:
        raw["server_version"] = str(getattr(client, "server_version", "") or "")
    except Exception:
        pass
    snap = snapshot(client, prefixes)
    view = {k: snap.get(k) for k in ("total_gb", "free_gb", "committed_gb", "available_gb", "license", "pool",
                                     "running_nodes", "errors")}
    view["labs"] = [{k: x.get(k) for k in ("running_nodes", "counted_nodes", "ram_gb", "ours")} for x in snap["labs"]]
    return redact_tree({"app_version": __version__, "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "cml": raw, "app_view": view})


def licensed_nodes(lab, platform: str = "iol") -> int:
    """Nodes of a lab that use a CML node license (unmanaged switches and external connectors do not)."""
    try:
        return sum(1 for d in sizing.node_definitions(lab, platform) if d not in UNCOUNTED)
    except Exception:
        return getattr(lab, "node_count", 0)


def _node_gb(n) -> float:
    try:
        ram = getattr(n, "ram", None)
    except Exception:
        ram = None
    gb = _gb(ram, "mib") if ram else None
    return gb if gb else sizing.RAM_GB.get(getattr(n, "node_definition", ""), sizing.UNKNOWN_GB)


def snapshot(client, prefixes=("CML-",)) -> dict:
    """What is running on the server now. Never raises; problems are listed in "errors"."""
    errors: list[str] = []
    total = free = None
    try:
        total, free = _memory(client.get_system_stats())
        if total is None:
            errors.append("the server did not report its memory")
    except Exception as e:
        errors.append(f"system stats: {_why(e)}")
    status = diag = None
    try:
        status = client.licensing.status()
    except Exception:
        pass      # non-admins cannot read licensing; that is normal
    try:
        from virl2_client.virl2_client import DiagnosticsCategory
        diag = client.get_diagnostics(DiagnosticsCategory.LICENSING)
    except Exception:
        pass      # older CML, non-admin or a fake client: count the running nodes instead
    saw_all = False
    labs = []
    try:
        try:
            all_labs = client.all_labs(show_all=True)
            saw_all = True
        except Exception:
            all_labs = client.all_labs(show_all=False)
        for lab in all_labs:
            try:
                nodes = lab.nodes()
            except Exception:
                nodes = []
            running = [n for n in nodes if getattr(n, "state", "") in ACTIVE]
            if not running:
                continue
            title = str(getattr(lab, "title", "") or "")
            labs.append({
                "id": lab.id, "title": title,
                "owner": str(getattr(lab, "owner_username", "") or ""),
                "running_nodes": len(running),
                "counted_nodes": sum(1 for n in running if getattr(n, "node_definition", "") not in UNCOUNTED),
                "ram_gb": round(sum(_node_gb(n) for n in running), 1),
                "ours": title.startswith(tuple(prefixes) + LEGACY_PREFIXES),
            })
    except Exception as e:
        errors.append(f"labs: {_why(e)}")
    labs.sort(key=lambda x: -x["ram_gb"])
    counted = sum(x["counted_nodes"] for x in labs)
    # every lab is only visible to an admin, who is also the only one who can read /licensing
    lic = _license(status, diag, counted if (saw_all and isinstance(status, dict)) else None)
    pool = _user_pool(client)
    pool.pop("raw_usage", None)
    committed = round(sum(x["ram_gb"] for x in labs), 1)
    available = None
    if free is not None:
        available = free if total is None else min(free, max(0.0, total - committed))
        available = round(available, 1)
    return {"ok": available is not None, "total_gb": total, "free_gb": free,
            "committed_gb": committed, "available_gb": available, "license": lic, "pool": pool, "labs": labs,
            "running_nodes": sum(x["counted_nodes"] for x in labs), "errors": errors, "at": time.time()}


def _why(e: Exception) -> str:
    from .config import redact
    return redact(f"{type(e).__name__}: {e}")[:200]


def verdict(snap: dict, need_gb: float, nodes: int, headroom_gb: float = DEFAULT_HEADROOM_GB,
            node_limit: int | None = None, own_title: str | None = None) -> dict:
    """Fit of a lab needing need_gb / nodes (license-using nodes) on top of snap. own_title: this lab's CML title
    (a rebuild frees it). Memory and nodes get their own verdict (3.3.1) so the UI can say which limit failed:
    {"level", "ram": {"level", "reason"}, "nodes": {"level", "reason", "in_use", "max"}, ...}."""
    own = next((x for x in snap.get("labs", []) if own_title and x["title"] == own_title), None)
    if own:     # (re)building this lab replaces the running copy: its RAM and nodes come back
        need_gb = max(0.0, need_gb - own["ram_gb"])
        nodes = max(0, nodes - own["counted_nodes"])
    freed = own["counted_nodes"] if own else 0

    # memory
    avail = snap.get("available_gb")
    margin = None
    if avail is None:
        ram = {"level": "unknown", "reason": "Could not read the server's free memory"
               + (f" ({snap['errors'][0]})" if snap.get("errors") else "") + "."}
    else:
        margin = round(avail - need_gb, 1)
        if margin < 0:
            ram = {"level": "nofit", "reason": f"Memory: needs about {need_gb:.0f} GB but only {avail:.0f} GB is free."}
        elif margin < headroom_gb:
            ram = {"level": "tight", "reason": f"Memory: leaves only {margin:.0f} GB free (less than the "
                                               f"{headroom_gb:g} GB headroom in Settings)."}
        else:
            ram = {"level": "fits", "reason": ""}

    # node licenses (and the optional node limit in Settings)
    lic = snap.get("license")
    nd = {"level": "fits", "reason": "", "note": "", "in_use": None, "max": None, "need": nodes}
    if lic and lic.get("known"):
        in_use = max(0, int(lic["in_use"]) - freed)
        nd.update(in_use=in_use, max=int(lic["max"]))
        if in_use + nodes > lic["max"]:
            nd.update(level="nofit", reason=f"Node licenses: needs {nodes}, but {in_use} of {lic['max']} are in use "
                                            f"({lic['max'] - in_use} free).")
    else:
        nd["level"] = "unknown"
        why = (lic or {}).get("note") or "CML did not report its license (only admins can read it)"
        nd["note"] = f"Node licenses: can't tell ({why}); this lab uses {nodes}."
    pool = snap.get("pool") or {}
    if nd["level"] != "nofit" and _int(pool.get("max")) and _int(pool.get("in_use")) is not None:
        p_use = max(0, int(pool["in_use"]) - freed)
        nd["pool"] = {"label": pool.get("label") or "", "max": int(pool["max"]), "in_use": p_use}
        if p_use + nodes > int(pool["max"]):
            nd.update(level="nofit", reason=f"Node licenses: your CML resource pool{' ' + repr(pool['label']) if pool.get('label') else ''}"
                                            f" allows {pool['max']} nodes and {p_use} are in use; this lab needs {nodes}.")
    if node_limit and nd["level"] != "nofit" and snap.get("running_nodes", 0) - freed + nodes > node_limit:
        nd.update(level="nofit", reason=f"Nodes: would exceed the node limit in Settings ({node_limit}).")

    level = "nofit" if "nofit" in (ram["level"], nd["level"]) else ram["level"]
    reasons = [r for r in (ram["reason"], nd["reason"]) if r]     # problems only; "can't tell" is in node_check
    failed = [k for k, v in (("memory", ram), ("nodes", nd)) if v["level"] == "nofit"]
    return {"level": level, "need_gb": round(need_gb, 1), "nodes": nodes, "margin_gb": margin,
            "headroom_gb": headroom_gb, "reasons": reasons, "running_copy": own, "ram": ram, "node_check": nd,
            "failed": failed}


class Cache:
    """Short-lived cache of snapshot() per CML login (library cards ask often; the pre-check asks fresh)."""

    def __init__(self, ttl: float = CACHE_SECONDS, clock=time.monotonic):
        self.ttl, self._clock, self._lock = ttl, clock, threading.Lock()
        self._v: dict = {}

    def get(self, key, compute, fresh: bool = False) -> dict:
        with self._lock:
            hit = self._v.get(key)
            if hit and not fresh and self._clock() - hit[0] < self.ttl:
                return dict(hit[1], cached=True)
        v = compute()
        with self._lock:
            self._v[key] = (self._clock(), v)
        return dict(v, cached=False)

    def clear(self) -> None:
        with self._lock:
            self._v.clear()


def find_cml_lab(client, cml_id: str):
    for show_all in (True, False):
        try:
            for lab in client.all_labs(show_all=show_all):
                if lab.id == cml_id:
                    return lab
        except Exception:
            continue
    return None


def stop_lab(client, cml_id: str, progress, wipe: bool = False, prefixes=("CML-",)) -> dict:
    """Stop a running CML lab (any lab this login can see) to free its memory; wipe only labs this app built
    (titled CML-... / ENCOR-...), because wiping discards the nodes' disks and configs."""
    lab = find_cml_lab(client, cml_id)
    if lab is None:
        raise RuntimeError(f"no CML lab with id {cml_id} (already removed?)")
    title = str(lab.title)
    ours = title.startswith(tuple(prefixes) + LEGACY_PREFIXES)
    if wipe and not ours:
        raise RuntimeError(f"refusing to wipe {title!r}: only labs built by this app (CML-...) are wiped; stop it instead")
    progress(f"Stopping {title}…")
    lab.stop(wait=True)
    if wipe:
        progress(f"Wiping {title} (node disks and configs are discarded)…")
        lab.wipe(wait=True)
    progress(f"{title}: {'stopped and wiped' if wipe else 'stopped'}")
    return {"id": cml_id, "title": title, "wiped": wipe}
