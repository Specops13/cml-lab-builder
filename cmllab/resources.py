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


def _memory(stats: dict) -> tuple[float | None, float | None]:
    """(total_gb, free_gb) summed over the compute hosts."""
    if not isinstance(stats, dict):
        return None, None
    mem = (stats.get("all") or {}).get("memory") if isinstance(stats.get("all"), dict) else None
    if not isinstance(mem, dict):
        total = free = 0.0
        found = False
        for c in (stats.get("computes") or {}).values():
            m = ((c or {}).get("stats") or {}).get("memory") or {}
            if "total" in m:
                found = True
                total += _gb(m.get("total"), "bytes") or 0.0
                free += _gb(m.get("free"), "bytes") or 0.0
        return (round(total, 1), round(free, 1)) if found else (None, None)
    total, free = _gb(mem.get("total"), "bytes"), _gb(mem.get("free"), "bytes")
    if free is None and total is not None and mem.get("used") is not None:
        free = total - (_gb(mem.get("used"), "bytes") or 0.0)
    return (round(total, 1) if total is not None else None, round(free, 1) if free is not None else None)


def _license(lic: dict) -> dict | None:
    """{"max": licensed nodes, "in_use": nodes counted now} from GET /licensing, or None."""
    feats = (lic or {}).get("features") if isinstance(lic, dict) else None
    if not isinstance(feats, list):
        return None
    mx = used = 0
    for f in feats:
        if not isinstance(f, dict):
            continue
        try:
            mx += int(f.get("max") or 0)
            used += int(f.get("in_use") or 0)
        except (TypeError, ValueError):
            continue
    return {"max": mx, "in_use": used} if mx > 0 else None


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
    lic = None
    try:
        lic = _license(client.licensing.status())
    except Exception:
        pass      # non-admins cannot read licensing; that is normal
    labs = []
    try:
        try:
            all_labs = client.all_labs(show_all=True)
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
    committed = round(sum(x["ram_gb"] for x in labs), 1)
    available = None
    if free is not None:
        available = free if total is None else min(free, max(0.0, total - committed))
        available = round(available, 1)
    return {"ok": available is not None, "total_gb": total, "free_gb": free,
            "committed_gb": committed, "available_gb": available, "license": lic, "labs": labs,
            "running_nodes": sum(x["counted_nodes"] for x in labs), "errors": errors, "at": time.time()}


def _why(e: Exception) -> str:
    from .config import redact
    return redact(f"{type(e).__name__}: {e}")[:200]


def verdict(snap: dict, need_gb: float, nodes: int, headroom_gb: float = DEFAULT_HEADROOM_GB,
            node_limit: int | None = None, own_title: str | None = None) -> dict:
    """Fit of a lab needing need_gb / nodes on top of snap. own_title: this lab's CML title (a rebuild frees it)."""
    own = next((x for x in snap.get("labs", []) if own_title and x["title"] == own_title), None)
    reasons = []
    level = "fits"
    avail = snap.get("available_gb")
    if own:     # (re)building this lab replaces the running copy: its RAM and nodes come back
        need_gb = max(0.0, need_gb - own["ram_gb"])
        nodes = max(0, nodes - own["counted_nodes"])
    margin = None
    if avail is None:
        level = "unknown"
        reasons.append("Could not read the server's free memory" + (f" ({snap['errors'][0]})" if snap.get("errors") else "") + ".")
    else:
        margin = round(avail - need_gb, 1)
        if margin < 0:
            level = "nofit"
            reasons.append(f"Needs about {need_gb:.0f} GB but only {avail:.0f} GB is free.")
        elif margin < headroom_gb:
            level = "tight"
            reasons.append(f"Leaves only {margin:.0f} GB free (less than the {headroom_gb:g} GB headroom in Settings).")
    lic = snap.get("license")
    if lic and lic["in_use"] + nodes > lic["max"]:
        level = "nofit"
        reasons.append(f"Needs {nodes} licensed nodes; {lic['in_use']} of {lic['max']} are in use.")
    if node_limit and snap.get("running_nodes", 0) - (own["counted_nodes"] if own else 0) + nodes > node_limit:
        level = "nofit"
        reasons.append(f"Would exceed the node limit in Settings ({node_limit}).")
    return {"level": level, "need_gb": round(need_gb, 1), "nodes": nodes, "margin_gb": margin,
            "headroom_gb": headroom_gb, "reasons": reasons, "running_copy": own}


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
