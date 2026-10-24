"""Local web UI (FastAPI). Binds to 127.0.0.1 by default; secrets stay in memory
(or OS keyring if the user opts in) and are never returned by the API."""
from __future__ import annotations

import mimetypes
import threading
from pathlib import Path

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import security
from .. import __version__, ai, autoupdate, catalog, config, courses, exam, faults, history, library, migrate, packs, progress, report, resources, service, sizing, snapshots, updates, walkthrough
from .. import solution as solution_mod
from ..cml_import import draft_from_topology
from .. import cml as _cml_mod
from ..platforms import get as get_platform, render
from ..prompt import build_prompt, json_schema
from ..templates import catalog as template_catalog

HERE = Path(__file__).parent

# Windows can map .js/.css to text/plain in the registry, which Python's mimetypes then reports;
# browsers refuse stylesheets (and, with nosniff, scripts) served that way. Register the right types.
for _type, _ext in (("text/javascript", ".js"), ("text/javascript", ".mjs"), ("text/css", ".css"),
                    ("application/json", ".json"), ("image/svg+xml", ".svg")):
    mimetypes.add_type(_type, _ext)


class LibInstall(BaseModel):
    file: str = ""
    url: str = ""
    index_url: str = ""          # empty: Settings > Library URL (default: the project's repo)
    sha256: str = ""
    replace: bool = False


class LibInstallSet(BaseModel):
    ids: list[str] = []
    starter: bool = False        # the recommended starter set from the library index
    updates: bool = False        # every installed library lab with a newer version in the library
    index_url: str = ""


class StopIn(BaseModel):
    wipe: bool = False
    confirm: bool = False


class SettingsIn(BaseModel):
    cml_url: str | None = None
    username: str | None = None
    password: str | None = None
    verify_tls: str | None = None
    console_host: str | None = None
    console_port: int | None = None
    grading_mode: str | None = None
    platform: str | None = None
    node_limit: int | None = None
    device_username: str | None = None
    device_password: str | None = None
    device_enable: str | None = None
    ai_preset: str | None = None
    ai_base_url: str | None = None
    ai_model: str | None = None
    ai_api_key: str | None = None
    show_help: bool | None = None
    check_updates: bool | None = None
    ram_heavy_gb: int | None = None
    resource_check: bool | None = None
    resource_headroom_gb: float | None = None
    library_url: str | None = None
    nxos_username: str | None = None
    nxos_password: str | None = None
    remember_password: bool = False
    remember_ai_key: bool = False


class YamlIn(BaseModel):
    yaml: str
    solution_cfg: str | None = None
    replace: bool = False
    strict: bool = False
    fixtures_from: str | None = None   # reuse recorded show outputs of this existing lab (builder edits)


class ObjIn(BaseModel):
    obj: dict


class DescIn(BaseModel):
    description: str = ""


class CmlDraftIn(BaseModel):
    lab_id: str


JOB_LABELS = {"build": "a lab build", "check": "grading", "test-live": "a live test", "break": "fault injection",
              "restore": "a snapshot restore", "snapshot": "a snapshot", "reset": "a lab reset",
              "destroy": "a lab teardown", "ai": "AI lab generation", "step-check": "a walkthrough step check",
              "step-apply": "applying a walkthrough step", "cml-stop": "stopping a CML lab"}


def create_app(store: config.SettingsStore | None = None, client_factory=None, runner_factory=None,
               config_factory=None, probe=None, persist: bool = True, ai_transport=None,
               library_fetch=None, update_fetch=None, update_http=None, auto_update: bool = False,
               restart=None, auto_restore: bool | None = None, console_factory=None, access_token: str | None = None,
               allowed_hosts=()) -> FastAPI:
    """auto_update=True (the desktop launcher) starts the background update checker; update_http / restart are
    test hooks for it (see autoupdate.Updater). auto_restore (default: same as auto_update) installs labs an older
    version bundled from the library in the background when they could not be copied from disk (migrate.py).
    access_token / allowed_hosts: see web/security.py (Host allowlist, CSRF, CSP and the optional access token)."""
    migrate.run_local()          # keep the labs 1.x bundled (copies them once into the user labs folder)
    store = store or config.SettingsStore()
    jobs = service.JobManager()

    def _busy() -> list[str]:
        """Work an update must not interrupt."""
        out = [f"{JOB_LABELS.get(j.kind, j.kind)} ({j.lab_id})" if not j.lab_id.startswith("__") else JOB_LABELS.get(j.kind, j.kind)
               for j in jobs.running()]
        out += [f"an exam ({lab})" for lab in exam.running()]
        return out

    updater = autoupdate.Updater(settings=store.get, fetch=update_http, busy=_busy, restart=restart)
    if auto_update:
        updater.start()
    fetch = library_fetch or library.http_fetch

    def _lib_url(u: str = "") -> str:
        return (u or "").strip() or store.get().library_url or library.DEFAULT_INDEX

    if (auto_update if auto_restore is None else auto_restore) and migrate.status()["state"] == "pending":
        threading.Thread(target=lambda: migrate.restore(_lib_url(), fetch, store.get().node_limit),
                         name="restore-labs", daemon=True).start()
    app = FastAPI(title="CML Lab Builder", version=__version__)
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    @app.middleware("http")
    async def no_stale_assets(request, call_next):
        """After an upgrade the browser must not reuse old JS/CSS/HTML: always revalidate.
        Static URLs also carry ?v=<version> (see index.html), so a new version is a new URL."""
        resp = await call_next(request)
        path = request.url.path
        if path == "/" or path.startswith(("/static/", "/api/")):
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
            if path.startswith("/static/"):
                ctype = mimetypes.guess_type(path)[0]
                if ctype and ctype.startswith(("text/", "application/json")):
                    resp.headers["Content-Type"] = ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("json") else "")
        return resp

    security.install(app, access_token=access_token, extra_hosts=allowed_hosts)   # outermost: runs first

    def _entry(lab_id):
        try:
            return catalog.entry(lab_id)
        except catalog.LabNotFound as e:
            raise HTTPException(404, str(e))

    def _need_cml(s):
        if not s.is_configured():
            raise HTTPException(400, "Configure CML URL, username and password on the Settings page first")

    def _not_updating():
        if updater.applying():
            raise HTTPException(409, "An update is being installed and the app restarts in a moment; try again then.")

    def _start(kind, lab_id, fn, need_cml=True):
        _not_updating()
        s = store.get()
        if need_cml:
            _need_cml(s)
        try:
            job = jobs.start(kind, lab_id, lambda p: fn(s, p))
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        return {"job_id": job.id}

    def _err(rep: packs.Report, status=400):
        return JSONResponse(rep.to_dict(), status_code=status)

    # ------------------------------------------------------------ pages
    @app.get("/", response_class=HTMLResponse)
    def index():
        html = (HERE / "templates" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html.replace("{{VERSION}}", __version__))

    @app.get("/api/health")
    def health():
        return {"ok": True, "version": __version__}

    def _ram(l, s=None) -> dict:
        s = s or store.get()
        r = sizing.estimate(l, s.platform, s.ram_heavy_gb)
        return {k: r[k] for k in ("gb", "estimate_gb", "label", "heavy", "tooltip", "source", "threshold_gb", "vcpus")}

    def _wt_brief(l) -> dict | None:
        if not l.is_walkthrough:
            return None
        st = walkthrough.status(l)
        return {k: st[k] for k in ("current", "required", "required_passed", "pct", "completed")} | {
            "steps": len(l.steps)}

    def _plain(lab_id: str, what: str):
        e = _entry(lab_id)
        if e.lab.is_walkthrough:
            raise HTTPException(400, f"{what} is not available for walkthrough labs (they are guided builds, not challenges)")
        return e

    def _walk(lab_id: str):
        e = _entry(lab_id)
        if not e.lab.is_walkthrough:
            raise HTTPException(400, "this lab is not a walkthrough")
        return e

    # ------------------------------------------------------------ catalog
    @app.get("/api/labs")
    def labs():
        """Never fails as a whole: a lab that can't be loaded or summarized is reported in "broken"."""
        errors: dict = {}
        out = []
        try:
            plat = get_platform(store.get().platform)
        except ValueError as e:
            errors["settings"] = f"{e}; showing IOL interface names"
            plat = get_platform("iol")
        s = store.get()
        for lid, e in catalog.entries(errors=errors).items():
            try:
                l = e.lab
                h = history.load(lid)
                wt = _wt_brief(l)
                out.append({"id": l.id, "title": render(l.title, plat), "summary": render(l.summary, plat),
                            "blueprint": l.blueprint,
                            "domain": l.domain, "difficulty": l.difficulty, "nodes": l.node_count,
                            "platforms": l.platforms, "source": e.source, "track": l.track,
                            "node_types": sorted({d for pf in l.platforms for d in sizing.node_definitions(l, pf)}),
                            "checks": {"live": len(l.checks_for("live")), "config": len(l.checks_for("config"))},
                            "faults": len(l.faults), "fault_active": bool(faults.active(lid)), "exam_active": bool(exam.active(lid)),
                            "best": max((x.get("score_pct") or 0 for x in h), default=None) if not wt else None,
                            "solved": bool(wt["completed"]) if wt else any(x.get("passed") for x in h),
                            "type": l.type, "walkthrough": wt, "ram": _ram(l, s), "version": l.version,
                            "library": e.source == "builtin" or bool(library.origin(lid)),
                            "update_available": lid in library.last_index().get("updates", [])})
            except Exception as ex:  # pragma: no cover - defensive
                errors[str(e.path)] = f"{type(ex).__name__}: {ex}"
        return {"labs": out, "broken": errors, "migration": migrate.status()}

    # ------------------------------------------------------------ data folder (moved in 2.1.0, see paths.py)
    @app.get("/api/data-folder")
    def data_folder():
        from .. import paths
        return {**paths.status(), "path": str(history.data_dir()), "boot_dir": str(paths.boot_dir())}

    @app.post("/api/data-folder/ack")
    def data_folder_ack():
        from .. import paths
        return paths.acknowledge()

    # ------------------------------------------------------------ labs from 1.x (see migrate.py)
    @app.get("/api/migration")
    def migration_status():
        return migrate.status()

    @app.post("/api/migration/restore")
    def migration_restore():
        return migrate.restore(_lib_url(), fetch, store.get().node_limit)

    @app.post("/api/migration/dismiss")
    def migration_dismiss():
        return migrate.dismiss()

    @app.get("/api/labs/{lab_id}")
    def lab(lab_id: str):
        e = _entry(lab_id)
        l = e.lab
        plat = get_platform(store.get().platform)
        fault = faults.public(l, faults.active(lab_id), plat)
        ex = exam.status(lab_id)
        hints = fault["hints"] if fault and fault["hints"] else solution_mod.hints(l, plat)
        if ex:
            ex["hints_shown"] = hints[:ex["hints_used"]]
        steps = None
        if l.is_walkthrough:
            steps = [{"id": st.id, "title": render(st.title, plat), "explain": render(st.explain, plat),
                      "optional": st.optional, "apply": bool(st.apply and st.config),
                      "config": {d: render(c, plat) for d, c in st.config.items()},
                      "verify": [{"device": v.device, "command": render(v.command, plat), "expect": render(v.expect, plat)}
                                 for v in st.verify],
                      "checks": [{"id": c.id, "mode": c.mode, "device": c.device,
                                  "description": render(c.description, plat)} for c in st.checks]}
                     for st in l.steps]
        return {"type": l.type, "steps": steps, "ram": _ram(l),
                "walkthrough": walkthrough.status(l) if l.is_walkthrough else None,
                "final_summary": walkthrough.summary(l, plat) if l.is_walkthrough else None,
                "exam": ex, "hints_total": len(hints), "default_exam_minutes": exam.default_minutes(l),
                "id": l.id, "title": render(l.title, plat), "summary": render(l.summary, plat),
                "source": e.source, "task": render(l.task, plat),
                "faults": len(l.faults), "fault": fault,
                "blueprint": l.blueprint, "domain": l.domain, "difficulty": l.difficulty, "nodes": l.node_count,
                "platforms": l.platforms, "author": l.author, "track": l.track,
                "node_list": [{"name": n.name, "definition": n.definition,
                               "os": _cml_mod.node_os(l).get(n.name, "ios")} for n in l.nodes],
                "has_solution": bool(catalog.load_solution(lab_id)),
                "has_solution_summary": bool(l.solution_summary.strip()),
                "hints": [] if ex else hints,          # withheld during an exam (served one by one, penalized)
                "checks": [{"id": c.id, "mode": c.mode, "description": render(c.description, plat),
                            "device": c.device, "hint": "" if ex else render(c.hint, plat)} for c in l.checks]}

    @app.post("/api/labs/{lab_id}/console-test")
    def console_test(lab_id: str, node: str):
        """Open one node's console step by step and report each stage with the raw console output."""
        e = _entry(lab_id)
        if node not in {n.name for n in e.lab.nodes}:
            raise HTTPException(404, f"no node {node!r} in {lab_id}")
        s = store.get()
        errs = s.validate()
        if errs:
            raise HTTPException(400, "; ".join(errs))
        from ..console import diagnose
        try:
            cl = service.make_cml(s, client_factory).find(e.lab)
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "stages": [{"name": "find the lab in CML", "ok": False, "detail": f"{type(ex).__name__}: {ex}"}], "tail": ""}
        if cl is None:
            return {"ok": False, "stages": [{"name": "find the lab in CML", "ok": False,
                                             "detail": "the lab is not built in CML (click Build first)"}], "tail": ""}
        return diagnose(s, cl.title, node, _cml_mod.node_os(e.lab).get(node, "ios"), client_factory=console_factory)

    # SSH host key of the console server (trust on first use, see console.py)
    @app.get("/api/console/hostkey")
    def console_hostkey():
        from ..console import stored_host_key
        s = store.get()
        host = s.effective_console_host
        return {"host": host, "port": s.console_port, "key": stored_host_key(host, s.console_port) if host else None}

    @app.post("/api/console/hostkey/forget")
    def console_hostkey_forget():
        from ..console import forget_host_key
        s = store.get()
        return {"forgotten": bool(s.effective_console_host) and forget_host_key(s.effective_console_host, s.console_port)}

    def _no_exam(lab_id: str):
        if exam.active(lab_id):
            raise HTTPException(403, "not available while an exam is running (submit or abort it first)")

    @app.post("/api/labs/{lab_id}/exam/start")
    def exam_start(lab_id: str, minutes: int | None = None, hints: str = "penalty", penalty: int = exam.DEFAULT_PENALTY):
        _not_updating()
        e = _plain(lab_id, "Exam mode")
        if exam.active(lab_id):
            raise HTTPException(409, "an exam is already running for this lab")
        try:
            return exam.start(e.lab, minutes, hints, penalty)
        except exam.ExamError as ex:
            raise HTTPException(400, str(ex))

    @app.post("/api/labs/{lab_id}/exam/hint")
    def exam_hint(lab_id: str):
        e = _entry(lab_id)
        plat = get_platform(store.get().platform)
        hints = solution_mod.hints(e.lab, plat)
        try:
            n = exam.use_hint(lab_id, len(hints))
        except exam.ExamError as ex:
            raise HTTPException(400, str(ex))
        return {"n": n, "total": len(hints), "hints": hints[:n], "exam": exam.status(lab_id)}

    @app.post("/api/labs/{lab_id}/exam/abort")
    def exam_abort(lab_id: str):
        _entry(lab_id)
        exam.clear(lab_id)
        return {"aborted": True}

    @app.get("/api/labs/{lab_id}/solution")
    def lab_solution(lab_id: str):
        """Solution summary (author-written or auto-generated) + per-device solution config.
        Only requested by the UI after Check (automatically at 100%, otherwise behind a confirm)."""
        e = _entry(lab_id)
        _no_exam(lab_id)
        plat = get_platform(store.get().platform)
        return solution_mod.reveal(e.lab, catalog.load_solution(lab_id), plat)

    @app.get("/api/labs/{lab_id}/source")
    def lab_source(lab_id: str):
        """lab.yaml text with the solution embedded (for the editor)."""
        e = _entry(lab_id)
        _no_exam(lab_id)
        data = yaml.safe_load((e.path / "lab.yaml").read_text(encoding="utf-8"))
        sol = catalog.load_solution(lab_id)
        if sol and not e.lab.is_walkthrough:      # a walkthrough's solution is its step configs
            data["solution"] = sol
        return {"yaml": ai.to_yaml_text(data), "source": e.source}

    @app.get("/api/labs/{lab_id}/export")
    def export(lab_id: str):
        _entry(lab_id)
        _no_exam(lab_id)
        return Response(packs.export_pack(lab_id), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{lab_id}{packs.PACK_EXT}"'})

    def _lib_err(e: Exception):
        if isinstance(e, packs.LabError):
            exists = any("already exists" in x for x in e.errors)
            return JSONResponse({"ok": False, "errors": e.errors, "warnings": e.warnings}, status_code=409 if exists else 400)
        status = 502 if str(e).startswith(("network error", "download failed")) else 400
        return JSONResponse({"ok": False, "errors": [str(e)], "warnings": []}, status_code=status)

    @app.post("/api/import")
    async def import_file(file: UploadFile = File(...), replace: bool = False):
        data = await file.read()
        if courses.is_course(file.filename or "", data):
            try:   # labs the course lists but doesn't bundle come from the library (when online)
                return library.install_course_file(data, _lib_url(), fetch, node_limit=store.get().node_limit, overwrite=replace)
            except (packs.LabError, library.LibraryError) as e:
                return _lib_err(e)
        try:
            pk = packs.read_upload(file.filename or "upload", data)
        except packs.LabError as e:
            return _err(packs.Report(False, None, None, e.errors, e.warnings, []))
        rep = packs.install(pk, node_limit=store.get().node_limit, overwrite=replace)
        if not rep.ok:
            exists = any("already exists" in x for x in rep.errors)
            return _err(rep, 409 if exists else 400)
        return rep.to_dict()

    # ------------------------------------------------------------ courses + online library
    def _best() -> dict:
        out = {}
        for lid, e in catalog.entries().items():
            if e.lab.is_walkthrough:     # completion, not a score
                out[lid] = 100.0 if walkthrough.status(e.lab)["completed"] else None
                continue
            h = history.load(lid)
            out[lid] = max((x.get("score_pct") or 0 for x in h), default=None)
        return out

    @app.get("/api/courses")
    def course_list():
        s = store.get()
        return {"courses": courses.list_courses(_best(), platform=s.platform, heavy_gb=s.ram_heavy_gb)}

    @app.delete("/api/courses/{course_id}")
    def course_delete(course_id: str, labs: bool = False):
        try:
            return {"ok": True, "removed_labs": courses.delete(course_id, remove_labs=labs)}
        except packs.LabError as e:
            raise HTTPException(404, "; ".join(e.errors))

    @app.get("/api/library")
    def library_index(url: str = ""):
        try:
            return library.index(_lib_url(url), fetch=fetch, heavy_gb=store.get().ram_heavy_gb)
        except (library.LibraryError, packs.LabError) as e:  # shown in the UI
            return _lib_err(e)

    @app.post("/api/library/install")
    def library_install(body: LibInstall):
        lim = store.get().node_limit
        try:
            if body.file:
                return library.install_item(body.file, url=_lib_url(body.index_url), fetch=fetch, node_limit=lim, overwrite=body.replace)
            if body.url:
                return library.install_url(body.url, body.sha256, fetch=fetch, node_limit=lim, overwrite=body.replace)
        except (library.LibraryError, packs.LabError) as e:
            return _lib_err(e)
        raise HTTPException(400, "give a library file or a URL")

    @app.post("/api/library/install-set")
    def library_install_set(body: LibInstallSet):
        """Several labs in one go: the starter set, a list of ids, or all available updates."""
        if not (body.ids or body.starter or body.updates):
            raise HTTPException(400, "give ids, starter or updates")
        try:
            r = library.install_many(body.ids, starter=body.starter, updates=body.updates, url=_lib_url(body.index_url),
                                     fetch=fetch, node_limit=store.get().node_limit)
        except (library.LibraryError, packs.LabError) as e:
            return _lib_err(e)
        if body.updates:
            library.last_index()["updates"] = [x for x in library.last_index().get("updates", []) if x not in r["installed"]]
        return r

    def _pack_from_body(body: YamlIn) -> packs.Pack:
        """Builder edits don't carry fixtures; reuse the source lab's recorded outputs while they still
        fit the edited lab, otherwise drop them (live checks are then syntax-checked only)."""
        pk = packs.Pack(body.yaml, body.solution_cfg)
        if not body.fixtures_from:
            return pk
        try:
            src = catalog.entry(body.fixtures_from)
            fx = {st: catalog.load_fixture(body.fixtures_from, st) for st in ("solved", "blank")}
        except Exception:
            return pk
        readme = src.path / "README.md"
        if readme.is_file():
            pk.readme = readme.read_text(encoding="utf-8")
        fx = {k: v for k, v in fx.items() if v}
        if not fx:
            return pk
        with_fx = packs.Pack(body.yaml, body.solution_cfg, fx, pk.readme)
        limit = store.get().node_limit
        if packs.lint(with_fx, node_limit=limit).ok or not packs.lint(pk, node_limit=limit).ok:
            return with_fx
        pk.warnings.append(f"recorded outputs (fixtures) of {body.fixtures_from} no longer match the edited "
                           "live checks and were dropped; live checks are syntax-checked only")
        return pk

    @app.post("/api/user-labs")
    def save_user_lab(body: YamlIn):
        pk = _pack_from_body(body)
        rep = packs.install(pk, node_limit=store.get().node_limit, overwrite=body.replace)
        if not rep.ok:
            return _err(rep, 409 if any("already exists" in x for x in rep.errors) else 400)
        return rep.to_dict()

    @app.delete("/api/user-labs/{lab_id}")
    def delete_user_lab(lab_id: str, clear_history: bool = False):
        """Removes the lab files. Results history and progress stay (re-installing the lab links them up again)
        unless clear_history=true."""
        _entry(lab_id)
        try:
            packs.delete_user_lab(lab_id)
        except packs.LabError as e:
            raise HTTPException(400, str(e))
        if clear_history:
            history.clear(lab_id)
        return {"deleted": lab_id, "history_cleared": clear_history}

    @app.post("/api/validate")
    def validate(body: YamlIn):
        rep = packs.lint(_pack_from_body(body), node_limit=store.get().node_limit,
                         strict=body.strict, builtin_ids=packs.builtin_ids())
        return rep.to_dict()

    @app.post("/api/yaml/dump")
    def yaml_dump(body: ObjIn):
        return {"yaml": ai.to_yaml_text(body.obj)}

    @app.post("/api/yaml/parse")
    def yaml_parse(body: YamlIn):
        try:
            data = yaml.safe_load(body.yaml)
        except yaml.YAMLError as e:
            return JSONResponse({"error": f"YAML syntax error: {e}"}, status_code=400)
        if not isinstance(data, dict):
            return JSONResponse({"error": "not a YAML mapping"}, status_code=400)
        return {"obj": data}

    @app.get("/api/templates")
    def templates():
        return template_catalog()

    @app.get("/api/schema")
    def schema():
        return json_schema()

    @app.get("/api/prompt")
    def prompt(description: str = ""):
        return {"prompt": build_prompt(description)}

    # ------------------------------------------------------------ history
    @app.get("/api/history/{lab_id}")
    def get_history(lab_id: str):
        return history.load(lab_id)

    @app.delete("/api/history/{lab_id}")
    def del_history(lab_id: str):
        history.clear(lab_id)
        return {"cleared": lab_id}

    # ------------------------------------------------------------ printable reports (print to PDF in the browser)
    @app.get("/report/labs/{lab_id}", response_class=HTMLResponse)
    def lab_report_page(lab_id: str, outputs: bool = False, name: str = ""):
        _entry(lab_id)
        _no_exam(lab_id)
        return HTMLResponse(report.lab_report(lab_id, outputs=outputs, student=name))

    @app.get("/report/progress", response_class=HTMLResponse)
    def progress_report_page(name: str = ""):
        return HTMLResponse(report.progress_report(student=name))

    @app.get("/api/progress")
    def get_progress():
        """Progress dashboard: mastery per ENCOR domain and blueprint item, streaks, time spent, weakest topics."""
        return progress.compute()

    # ------------------------------------------------------------ settings
    @app.get("/api/update-check")
    def update_check():
        """One GET to the GitHub Releases API; only called on a click or when check_updates is on."""
        try:
            return updates.check(__version__, fetch=update_fetch or updates.fetch, url=updates.release_url())
        except library.LibraryError as e:
            return JSONResponse({"error": str(e), "current": __version__, "url": updates.RELEASES_PAGE}, status_code=502)

    @app.get("/api/update/status")
    def update_status():
        """Running app code, runtime version, installed patch, rollback/restart state (no network)."""
        return updates.status()

    @app.post("/api/update/install")
    def update_install():
        """Download, verify (SHA256SUMS + manifest) and install the latest release's app patch."""
        try:
            return updates.install(__version__, fetch=update_fetch or updates.fetch)
        except updates.UpdateError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except library.LibraryError as e:
            return JSONResponse({"error": str(e)}, status_code=502)

    # ---- automatic updates: background check + staged patch, the prompt answers, idle-gated install
    def _upd_err(e: Exception):
        code = 502 if isinstance(e, library.LibraryError) and not isinstance(e, updates.UpdateError) else 400
        return JSONResponse({"error": str(e)}, status_code=code)

    @app.get("/api/update/auto")
    def update_auto():
        """Prompt state: staged offer, full-download banner, Update now progress, 'Updated to x' after a restart."""
        return updater.state()

    @app.post("/api/update/check")
    def update_check_now():
        """Manual check (Check now): from source it only reports; packaged, it also downloads + verifies the patch,
        and may offer a skipped or rolled-back version again."""
        try:
            if not updates.patchable()[0]:
                info = updates.check(__version__, fetch=update_fetch or updates.fetch, url=updates.release_url())
                return {"status": "source", "info": info, "state": updater.state()}
            return {**updater.check(manual=True), "state": updater.state()}
        except (library.LibraryError, updates.UpdateError) as e:
            return _upd_err(e)

    @app.post("/api/update/apply")
    def update_apply(version: str):
        """Update now: install as soon as no build / grading / snapshot / fault / exam is running, then restart."""
        try:
            return updater.apply(version)
        except updates.UpdateError as e:
            return _upd_err(e)

    @app.post("/api/update/cancel")
    def update_cancel():
        return updater.cancel()

    @app.post("/api/update/later")
    def update_later():
        return updater.later()

    @app.post("/api/update/skip")
    def update_skip(version: str):
        return updater.skip(version)

    @app.post("/api/update/dismiss-full")
    def update_dismiss_full(version: str):
        return updater.dismiss_full(version)

    @app.post("/api/update/ack")
    def update_ack():
        return updater.ack()

    @app.post("/api/update/rollback")
    def update_rollback():
        try:
            return updates.rollback()
        except updates.UpdateError as e:
            return JSONResponse({"error": str(e)}, status_code=400)

    @app.post("/api/update/restart")
    def update_restart():
        """Packaged app only: stop and start again on the same port (the open page reconnects)."""
        from .. import launcher
        try:
            launcher.request_restart()
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"restarting": True}

    @app.get("/api/settings")
    def get_settings():
        return store.get().public_dict()

    @app.post("/api/settings")
    def set_settings(body: SettingsIn):
        data = body.model_dump(exclude_none=True)
        remember = data.pop("remember_password", False)
        remember_ai = data.pop("remember_ai_key", False)
        before = store.get().check_updates
        try:
            s = store.update(**data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if s.check_updates != before:
            updater.wake()
        saved = config.keyring_set(s.username, s.password) if (remember and s.username and s.password) else False
        if saved:   # the device / NX-OS logins are remembered together with the CML password (3.3.0)
            for k in ("device_password", "device_enable", "nxos_password"):
                if getattr(s, k) and getattr(s, k) != "cisco":
                    config.keyring_set("device:" + k, getattr(s, k))
        ai_saved = (config.keyring_set("ai-key:" + s.ai_base_url, s.ai_api_key)
                    if (remember_ai and s.ai_base_url and s.ai_api_key) else False)
        out = s.public_dict()
        out["keyring_saved"] = saved
        out["secret_store"] = config.secret_backend() if (saved or ai_saved) else None
        out["ai_keyring_saved"] = ai_saved
        if persist:
            try:
                out["settings_file"] = str(config.save_settings(s))
            except OSError as e:
                out["settings_file_error"] = str(e)
        return out

    # ------------------------------------------------------------ CML actions
    @app.post("/api/labs/{lab_id}/build")
    def build(lab_id: str, rebuild: bool = False):
        _entry(lab_id)
        return _start("build", lab_id, lambda s, p: service.do_build(s, lab_id, p, rebuild=rebuild, client_factory=client_factory))

    @app.post("/api/labs/{lab_id}/check")
    def check(lab_id: str, mode: str | None = None, hints_used: int | None = None, elapsed_s: int | None = None,
              revealed: bool = False):
        _entry(lab_id)
        if mode not in (None, "auto", "live", "config"):
            raise HTTPException(400, "mode must be auto, live or config")
        extra = {}
        if elapsed_s is not None:
            extra["elapsed_s"] = max(0, min(int(elapsed_s), 30 * 24 * 3600))
        if revealed:
            extra["revealed"] = True

        if _entry(lab_id).lab.is_walkthrough:
            return wt_check_all(lab_id)

        def fn(s, p):
            m = mode or s.grading_mode
            runner = runner_factory(s, lab_id) if (runner_factory and m != "config") else None
            src = config_factory(s, lab_id) if config_factory else None
            return service.do_check(s, lab_id, p, client_factory=client_factory, runner=runner,
                                    config_source=src, mode=m, probe=probe, hints_used=hints_used, extra=extra)
        return _start("check", lab_id, fn)

    # ------------------------------------------------------------ walkthroughs
    @app.get("/api/labs/{lab_id}/walkthrough")
    def wt_status(lab_id: str):
        return walkthrough.status(_walk(lab_id).lab)

    @app.post("/api/labs/{lab_id}/walkthrough/step")
    def wt_goto(lab_id: str, index: int):
        """Remember the step the student is on (index == number of steps: the final summary)."""
        return walkthrough.set_current(_walk(lab_id).lab, index)

    @app.post("/api/labs/{lab_id}/walkthrough/reset")
    def wt_reset(lab_id: str):
        return walkthrough.reset(_walk(lab_id).lab)

    def _wt_kw(s, lab_id):
        runner = runner_factory(s, lab_id) if (runner_factory and s.grading_mode != "config") else None
        src = config_factory(s, lab_id) if config_factory else None
        return {"runner": runner, "config_source": src, "probe": probe, "client_factory": client_factory}

    @app.post("/api/labs/{lab_id}/steps/{step_id}/check")
    def wt_check(lab_id: str, step_id: str):
        e = _walk(lab_id)
        try:
            st = e.lab.step(step_id)
        except KeyError:
            raise HTTPException(404, f"unknown step {step_id}")
        if not st.checks:
            raise HTTPException(400, "this step has nothing to check")
        return _start("step-check", lab_id,
                      lambda s, p: walkthrough.check_step(s, lab_id, step_id, p, lab=e.lab, **_wt_kw(s, lab_id)))

    @app.post("/api/labs/{lab_id}/walkthrough/check-all")
    def wt_check_all(lab_id: str):
        e = _walk(lab_id)
        return _start("step-check", lab_id,
                      lambda s, p: walkthrough.check_all(s, lab_id, p, lab=e.lab, **_wt_kw(s, lab_id)))

    @app.post("/api/labs/{lab_id}/steps/{step_id}/apply")
    def wt_apply(lab_id: str, step_id: str):
        """Type the step's config into the devices over the CML console (the UI asks for confirmation first)."""
        e = _walk(lab_id)
        try:
            st = e.lab.step(step_id)
        except KeyError:
            raise HTTPException(404, f"unknown step {step_id}")
        if not (st.apply and st.config):
            raise HTTPException(400, "this step has no config to apply")

        def fn(s, p):
            runner = runner_factory(s, lab_id) if runner_factory else None
            return walkthrough.apply_step(s, lab_id, step_id, p, runner=runner, client_factory=client_factory, lab=e.lab)
        return _start("step-apply", lab_id, fn)

    @app.post("/api/labs/{lab_id}/test-live")
    def test_live(lab_id: str, mode: str = "auto"):
        e = _entry(lab_id)
        sol = catalog.load_solution(lab_id)
        if not sol:
            raise HTTPException(400, "this lab has no reference solution")

        def fn(s, p):
            runner = runner_factory(s, lab_id, True) if (runner_factory and mode != "config") else None
            src = config_factory(s, lab_id, True) if config_factory else None
            return service.do_test_live(s, e.lab, sol, p, client_factory=client_factory, mode=mode,
                                        runner=runner, config_source=src, probe=probe)
        return _start("test-live", lab_id, fn)

    @app.post("/api/labs/{lab_id}/break")
    def break_lab(lab_id: str, fault: str | None = None):
        """Break my lab: rebuild with the solution plus one random predefined fault."""
        e = _plain(lab_id, "Break my lab")
        if not e.lab.faults:
            raise HTTPException(400, "this lab has no predefined faults")
        _no_exam(lab_id)
        if not catalog.load_solution(lab_id):
            raise HTTPException(400, "this lab has no reference solution")
        if fault:
            try:
                faults.get(e.lab, fault)
            except faults.FaultError as ex:
                raise HTTPException(400, str(ex))
        return _start("break", lab_id, lambda s, p: service.do_break(s, lab_id, p, fault_id=fault, client_factory=client_factory))

    @app.post("/api/labs/{lab_id}/fault/end")
    def fault_end(lab_id: str):
        _entry(lab_id)
        faults.clear(lab_id)
        return {"ended": True}

    @app.post("/api/labs/{lab_id}/fault/reveal")
    def fault_reveal(lab_id: str):
        """Give up on the current fault: shows its cause and fix (recorded as revealed)."""
        e = _entry(lab_id)
        st = faults.active(lab_id)
        if not st:
            raise HTTPException(400, "no fault is active for this lab")
        faults.mark_revealed(lab_id)
        return faults.reveal(e.lab, faults.get(e.lab, st["fault_id"]), get_platform(store.get().platform))

    # ------------------------------------------------------------ config snapshots
    @app.get("/api/labs/{lab_id}/snapshots")
    def snapshot_list(lab_id: str):
        _entry(lab_id)
        return {"snapshots": snapshots.list_snapshots(lab_id), "max": snapshots.MAX_PER_LAB}

    @app.get("/api/labs/{lab_id}/snapshots/{name}")
    def snapshot_get(lab_id: str, name: str, fmt: str = "json"):
        _entry(lab_id)
        _no_exam(lab_id)
        try:
            snap = snapshots.load(lab_id, name)
        except snapshots.SnapshotError as e:
            raise HTTPException(404, str(e))
        if fmt == "cfg":
            return Response(snapshots.as_cfg(snap), media_type="text/plain",
                            headers={"Content-Disposition": f'attachment; filename="{lab_id}-{name}.cfg"'})
        return snap

    @app.post("/api/labs/{lab_id}/snapshots")
    def snapshot_save(lab_id: str, name: str = "", note: str = "", replace: bool = False):
        _entry(lab_id)
        _no_exam(lab_id)
        try:
            name = snapshots.check_name(name) if name else snapshots.default_name()
        except snapshots.SnapshotError as e:
            raise HTTPException(400, str(e))
        if not replace and any(x["name"] == name for x in snapshots.list_snapshots(lab_id)):
            raise HTTPException(409, f"a snapshot named {name!r} already exists")

        def fn(s, p):
            src = config_factory(s, lab_id) if config_factory else None
            return service.do_snapshot_save(s, lab_id, name, p, client_factory=client_factory, config_source=src,
                                            note=note, overwrite=replace)
        return _start("snapshot", lab_id, fn)

    @app.post("/api/labs/{lab_id}/snapshots/{name}/restore")
    def snapshot_restore(lab_id: str, name: str):
        _entry(lab_id)
        _no_exam(lab_id)
        try:
            snapshots.load(lab_id, name)
        except snapshots.SnapshotError as e:
            raise HTTPException(404, str(e))
        return _start("restore", lab_id, lambda s, p: service.do_snapshot_restore(s, lab_id, name, p, client_factory=client_factory))

    @app.delete("/api/labs/{lab_id}/snapshots/{name}")
    def snapshot_delete(lab_id: str, name: str):
        _entry(lab_id)
        try:
            snapshots.delete(lab_id, name)
        except snapshots.SnapshotError as e:
            raise HTTPException(404, str(e))
        return {"deleted": name}

    @app.post("/api/labs/{lab_id}/reset")
    def reset(lab_id: str):
        _entry(lab_id)
        return _start("reset", lab_id, lambda s, p: service.do_reset(s, lab_id, p, client_factory=client_factory))

    @app.post("/api/labs/{lab_id}/destroy")
    def destroy(lab_id: str):
        _entry(lab_id)
        return _start("destroy", lab_id, lambda s, p: service.do_destroy(s, lab_id, p, client_factory=client_factory))

    @app.get("/api/labs/{lab_id}/status")
    def status(lab_id: str):
        _entry(lab_id)
        s = store.get()
        if not s.is_configured():
            return {"configured": False}
        try:
            st = service.do_status(s, lab_id, client_factory=client_factory)
        except Exception as e:
            return {"configured": True, "error": f"{type(e).__name__}: {e}"}
        st["configured"] = True
        return st

    # ------------------------------------------------------------ resource pre-check (3.3.0, resources.py)
    res_cache = resources.Cache()

    def _snapshot(s, fresh=False) -> dict:
        def compute():
            try:
                return resources.snapshot(service.make_cml(s, client_factory).client, (s.lab_prefix,))
            except Exception as e:
                return {"ok": False, "errors": [config.redact(f"{type(e).__name__}: {e}")[:300]], "labs": [],
                        "available_gb": None, "total_gb": None, "free_gb": None, "license": None, "running_nodes": 0}
        return res_cache.get((s.cml_url, s.username), compute, fresh=fresh)

    @app.get("/api/resources")
    def cml_resources(fresh: bool = False):
        s = store.get()
        if not s.is_configured():
            return {"configured": False, "enabled": s.resource_check}
        out = _snapshot(s, fresh)
        out.update(configured=True, enabled=s.resource_check, headroom_gb=float(s.resource_headroom_gb),
                   node_limit=s.node_limit)
        return out

    @app.get("/api/resources/debug")
    def cml_resources_debug():
        """Redacted raw CML data behind the resource check, for bug reports (Copy diagnostics)."""
        s = store.get()
        if not s.is_configured():
            return {"configured": False}
        try:
            dump = resources.debug_dump(service.make_cml(s, client_factory).client, (s.lab_prefix,))
        except Exception as e:
            dump = {"error": config.redact(f"{type(e).__name__}: {e}")[:300]}
        return {"configured": True, "dump": dump}

    @app.get("/api/labs/{lab_id}/precheck")
    def precheck(lab_id: str):
        e = _entry(lab_id)
        s = store.get()
        if not s.is_configured():
            return {"configured": False, "enabled": s.resource_check}
        if not s.resource_check:
            return {"configured": True, "enabled": False}
        snap = _snapshot(s, fresh=True)
        est = sizing.estimate(e.lab, s.platform, s.ram_heavy_gb)
        v = resources.verdict(snap, est["gb"], resources.licensed_nodes(e.lab, s.platform),
                              float(s.resource_headroom_gb), s.node_limit,
                              own_title=_cml_mod.lab_title(e.lab, s.lab_prefix))
        return {"configured": True, "enabled": True, "snapshot": snap, "verdict": v, "ram": est}

    @app.post("/api/cml/labs/{cml_id}/stop")
    def cml_stop(cml_id: str, body: StopIn):
        if not body.confirm:
            raise HTTPException(400, "confirm=true is required (stopping a lab interrupts whoever uses it)")

        def fn(s, p):
            try:
                return resources.stop_lab(service.make_cml(s, client_factory).client, cml_id, p, wipe=body.wipe,
                                          prefixes=(s.lab_prefix,))
            finally:
                res_cache.clear()
        return _start("cml-stop", "cml:" + cml_id, fn)

    @app.get("/api/cml/labs")
    def cml_labs():
        s = store.get()
        _need_cml(s)
        try:
            return service.make_cml(s, client_factory).list_labs()
        except Exception as e:
            raise HTTPException(502, f"{type(e).__name__}: {e}")

    @app.post("/api/cml/draft")
    def cml_draft(body: CmlDraftIn):
        s = store.get()
        _need_cml(s)
        try:
            topo, title = service.make_cml(s, client_factory).download(body.lab_id)
            draft, warnings = draft_from_topology(topo, title)
        except Exception as e:
            raise HTTPException(400, f"{type(e).__name__}: {e}")
        return {"obj": draft, "yaml": ai.to_yaml_text(draft), "warnings": warnings}

    # ------------------------------------------------------------ AI (optional)
    @app.get("/api/ai/presets")
    def ai_presets():
        return ai.PRESETS

    @app.post("/api/ai/generate")
    def ai_generate(body: DescIn):
        s = store.get()
        if not (s.ai_base_url and s.ai_model):
            raise HTTPException(400, "Configure the AI provider (base URL and model) in Settings > AI generator first")
        if not body.description.strip():
            raise HTTPException(400, "Describe the lab you want")

        def fn(st, p):
            return ai.generate(body.description, st.ai_base_url, st.ai_model, st.ai_api_key or None,
                               node_limit=st.node_limit, transport=ai_transport, progress=p)
        return _start("ai", "__ai__", fn, need_cml=False)

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        j = jobs.get(job_id)
        if not j:
            raise HTTPException(404, "unknown job")
        return {"id": j.id, "kind": j.kind, "lab_id": j.lab_id, "state": j.state,
                "log": j.log, "result": j.result, "error": j.error}

    return app
