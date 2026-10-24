"""Printable HTML reports (print to PDF from the browser): a lab report for the latest check plus its attempt
history, and a progress report over all labs. Self-contained pages: inline CSS, no scripts beyond window.print()."""
from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from . import __version__, blueprint, catalog, history, progress

TEMPLATES = Path(__file__).parent / "web" / "templates"
MAX_OUTPUT = 4000
_env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
def _md(text: str) -> Markup:
    """Tiny, safe Markdown for solution summaries: escape everything, then ``` fences, **bold**, `code`, paragraphs."""
    out = []
    for i, part in enumerate(re.split(r"```[a-z]*\n?", text or "")):
        if i % 2:
            out.append(f"<pre>{html.escape(part.strip(chr(10)))}</pre>")
            continue
        for para in re.split(r"\n\s*\n", part.strip()):
            if para.strip():
                t = html.escape(para.strip())
                t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
                t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
                out.append("<p>" + t.replace("\n", "<br>") + "</p>")
    return Markup("".join(out))  # noqa: S704 - every piece was html.escape()d above


_env.filters["md"] = _md
_env.filters["dur"] = lambda s: "-" if not s else f"{int(s) // 3600}:{int(s) % 3600 // 60:02d}:{int(s) % 60:02d}"


def _file(lab_id: str) -> Path:
    return history.data_dir() / "reports" / f"{lab_id}.json"


def save_last(lab_id: str, rep: dict) -> None:
    """Keep the full result of the latest check (outputs trimmed) for the lab report."""
    d = json.loads(json.dumps(rep, default=str))
    for r in d.get("results", []):
        out = r.get("output") or ""
        if len(out) > MAX_OUTPUT:
            r["output"] = out[:MAX_OUTPUT] + f"\n... ({len(out) - MAX_OUTPUT} more characters)"
    d["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
    f = _file(lab_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(d), encoding="utf-8")


def load_last(lab_id: str) -> dict | None:
    try:
        d = json.loads(_file(lab_id).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def clear_last(lab_id: str) -> None:
    try:
        _file(lab_id).unlink()
    except FileNotFoundError:
        pass


def lab_report(lab_id: str, outputs: bool = False, student: str = "") -> str:
    e = catalog.entry(lab_id)
    lab = e.lab
    h = history.load(lab_id)
    last = load_last(lab_id)
    best = max((progress.attempt_score(x) for x in h), default=None)
    return _env.get_template("report_lab.html").render(
        lab=lab, source=e.source, items=[(b, blueprint.title(b)) for b in lab.blueprint], last=last, history=list(reversed(h)),
        best=best, solved=any(x.get("passed") for x in h), time_s=progress.lab_time(h), outputs=outputs,
        student=student[:80], generated=time.strftime("%Y-%m-%d %H:%M"), version=__version__, bp_version=blueprint.VERSION)


def progress_report(student: str = "") -> str:
    p = progress.compute()
    return _env.get_template("report_progress.html").render(
        p=p, student=student[:80], generated=time.strftime("%Y-%m-%d %H:%M"), version=__version__)
