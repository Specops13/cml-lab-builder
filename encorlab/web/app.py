"""Local web UI (FastAPI). Binds to 127.0.0.1 by default; secrets stay in memory
(or OS keyring if the user opts in) and are never returned by the API."""
from __future__ import annotations

import mimetypes
from pathlib import Path

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__, ai, catalog, config, courses, exam, faults, history, library, packs, progress, service, updates
from .. import solution as solution_mod
from ..cml_import import draft_from_topology
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
    index_url: str = library.DEFAULT_INDEX
    sha256: str = ""
    replace: bool = False


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


def create_app(store: config.SettingsStore | None = None, client_factory=None, runner_factory=None,
               config_factory=None, probe=None, persist: bool = True, ai_transport=None,
               library_fetch=None, update_fetch=None) -> FastAPI:
    store = store or config.SettingsStore()
    jobs = service.JobManager()
    app = FastAPI(title="ENCOR Lab Builder", version=__version__)
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

    def _entry(lab_id):
        try:
            return catalog.entry(lab_id)
        except catalog.LabNotFound as e:
            raise HTTPException(404, str(e))

    def _need_cml(s):
        if not s.is_configured():
            raise HTTPException(400, "Configure CML URL, username and password on the Settings page first")

    def _start(kind, lab_id, fn, need_cml=True):
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
        for lid, e in catalog.entries(errors=errors).items():
            try:
                l = e.lab
                h = history.load(lid)
                out.append({"id": l.id, "title": render(l.title, plat), "summary": render(l.summary, plat),
                            "blueprint": l.blueprint,
                            "domain": l.domain, "difficulty": l.difficulty, "nodes": l.node_count,
                            "platforms": l.platforms, "source": e.source,
                            "checks": {"live": len(l.checks_for("live")), "config": len(l.checks_for("config"))},
                            "faults": len(l.faults), "fault_active": bool(faults.active(lid)), "exam_active": bool(exam.active(lid)),
                            "best": max((x.get("score_pct") or 0 for x in h), default=None),
                            "solved": any(x.get("passed") for x in h)})
            except Exception as ex:  # pragma: no cover - defensive
                errors[str(e.path)] = f"{type(ex).__name__}: {ex}"
        return {"labs": out, "broken": errors}

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
        return {"exam": ex, "hints_total": len(hints), "default_exam_minutes": exam.default_minutes(l),
                "id": l.id, "title": render(l.title, plat), "summary": render(l.summary, plat),
                "source": e.source, "task": render(l.task, plat),
                "faults": len(l.faults), "fault": fault,
                "blueprint": l.blueprint, "domain": l.domain, "difficulty": l.difficulty, "nodes": l.node_count,
                "platforms": l.platforms, "author": l.author,
                "has_solution": bool(catalog.load_solution(lab_id)),
                "has_solution_summary": bool(l.solution_summary.strip()),
                "hints": [] if ex else hints,          # withheld during an exam (served one by one, penalized)
                "checks": [{"id": c.id, "mode": c.mode, "description": render(c.description, plat),
                            "device": c.device, "hint": "" if ex else render(c.hint, plat)} for c in l.checks]}

    def _no_exam(lab_id: str):
        if exam.active(lab_id):
            raise HTTPException(403, "not available while an exam is running (submit or abort it first)")

    @app.post("/api/labs/{lab_id}/exam/start")
    def exam_start(lab_id: str, minutes: int | None = None, hints: str = "penalty", penalty: int = exam.DEFAULT_PENALTY):
        e = _entry(lab_id)
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
        if sol:
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

    fetch = library_fetch or library.http_fetch

    @app.post("/api/import")
    async def import_file(file: UploadFile = File(...), replace: bool = False):
        data = await file.read()
        if courses.is_course(file.filename or "", data):
            try:
                return courses.install(data, node_limit=store.get().node_limit, overwrite=replace)
            except packs.LabError as e:
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
        for lid in catalog.entries():
            h = history.load(lid)
            out[lid] = max((x.get("score_pct") or 0 for x in h), default=None)
        return out

    @app.get("/api/courses")
    def course_list():
        return {"courses": courses.list_courses(_best())}

    @app.delete("/api/courses/{course_id}")
    def course_delete(course_id: str, labs: bool = False):
        try:
            return {"ok": True, "removed_labs": courses.delete(course_id, remove_labs=labs)}
        except packs.LabError as e:
            raise HTTPException(404, "; ".join(e.errors))

    @app.get("/api/library")
    def library_index(url: str = library.DEFAULT_INDEX):
        try:
            return library.index(url, fetch=fetch)
        except (library.LibraryError, packs.LabError) as e:  # shown in the UI
            return _lib_err(e)

    @app.post("/api/library/install")
    def library_install(body: LibInstall):
        lim = store.get().node_limit
        try:
            if body.file:
                return library.install_item(body.file, url=body.index_url, fetch=fetch, node_limit=lim, overwrite=body.replace)
            if body.url:
                return library.install_url(body.url, body.sha256, fetch=fetch, node_limit=lim, overwrite=body.replace)
        except (library.LibraryError, packs.LabError) as e:
            return _lib_err(e)
        raise HTTPException(400, "give a library file or a URL")

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
    def delete_user_lab(lab_id: str):
        _entry(lab_id)
        try:
            packs.delete_user_lab(lab_id)
        except packs.LabError as e:
            raise HTTPException(400, str(e))
        history.clear(lab_id)
        return {"deleted": lab_id}

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

    @app.get("/api/progress")
    def get_progress():
        """Progress dashboard: mastery per ENCOR domain and blueprint item, streaks, time spent, weakest topics."""
        return progress.compute()

    # ------------------------------------------------------------ settings
    @app.get("/api/update-check")
    def update_check():
        """One GET to the GitHub Releases API; only called on a click or when check_updates is on."""
        try:
            return updates.check(__version__, fetch=update_fetch or library.http_fetch)
        except library.LibraryError as e:
            return JSONResponse({"error": str(e), "current": __version__, "url": updates.RELEASES_PAGE}, status_code=502)

    @app.get("/api/settings")
    def get_settings():
        return store.get().public_dict()

    @app.post("/api/settings")
    def set_settings(body: SettingsIn):
        data = body.model_dump(exclude_none=True)
        remember = data.pop("remember_password", False)
        remember_ai = data.pop("remember_ai_key", False)
        try:
            s = store.update(**data)
        except ValueError as e:
            raise HTTPException(400, str(e))
        saved = config.keyring_set(s.username, s.password) if (remember and s.username and s.password) else False
        ai_saved = (config.keyring_set("ai-key:" + s.ai_base_url, s.ai_api_key)
                    if (remember_ai and s.ai_base_url and s.ai_api_key) else False)
        out = s.public_dict()
        out["keyring_saved"] = saved
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

        def fn(s, p):
            m = mode or s.grading_mode
            runner = runner_factory(s, lab_id) if (runner_factory and m != "config") else None
            src = config_factory(s, lab_id) if config_factory else None
            return service.do_check(s, lab_id, p, client_factory=client_factory, runner=runner,
                                    config_source=src, mode=m, probe=probe, hints_used=hints_used, extra=extra)
        return _start("check", lab_id, fn)

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
        e = _entry(lab_id)
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
