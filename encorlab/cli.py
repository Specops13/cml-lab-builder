"""Command line interface: encorlab <command>  (or python -m encorlab <command>)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__, catalog, config, courses, history, library, packs, service
from .platforms import get as get_platform, render
from .render import to_yaml

app = typer.Typer(add_completion=False, help=f"ENCOR Lab Builder {__version__}: build CCNP ENCOR labs in CML 2.9 and grade them.")


@app.callback()
def _main():
    """ENCOR Lab Builder command line."""
    from . import migrate
    st = migrate.run_local()      # keep the labs 1.x bundled (once, see migrate.py)
    if st.get("state") == "pending" and st.get("pending"):
        typer.echo(f"note: {len(st.get('pending', []))} lab(s) from your previous version still need to be restored "
                   "from the online library: encorlab library restore", err=True)


def _settings():
    s = config.from_env()
    errs = s.validate()
    if errs:
        raise typer.BadParameter("; ".join(errs))
    return s


def _p(msg: str):
    typer.echo("  " + msg)


def _print_report(rep: packs.Report, label: str) -> None:
    typer.echo(f"{'OK  ' if rep.ok else 'FAIL'} {label}  ({rep.lab_id or '?'}: {rep.title or ''})")
    for r in rep.results:
        typer.echo(f"     {r['platform']:5} {r['mode']:6} solution={r['solution_pct']}% blank={r['blank_pct']}%")
    for e in rep.errors:
        typer.echo(f"     ERROR: {e}")
    for w in rep.warnings:
        typer.echo(f"     warning: {w}")


@app.command()
def version():
    """Show the version."""
    typer.echo(__version__)


@app.command("list")
def list_labs():
    """List the installed labs."""
    from . import sizing
    s = config.from_env()
    plat = get_platform(s.platform)
    es = catalog.entries()
    if not es:
        typer.echo("no labs installed yet. Labs come from the online library:\n"
                   "  encorlab library install --starter     the recommended starter set\n"
                   "  encorlab library list                  everything the library offers\n"
                   "  encorlab import <file.encorlab>        a lab pack you downloaded")
    for lid, e in es.items():
        lab = e.lab
        fl = f"  faults:{len(lab.faults)}" if lab.faults else ""
        r = sizing.estimate(lab, s.platform, s.ram_heavy_gb)
        ram = f"RAM heavy {r['label']}" if r["heavy"] else r["label"]
        kind = "  [walkthrough]" if lab.is_walkthrough else ""
        typer.echo(f"{lid:28} {e.source:7} {lab.node_count} nodes  d{lab.difficulty}  {ram:>9}  "
                   f"[{', '.join(lab.blueprint)}]  {render(lab.title, plat)}{fl}{kind}")


@app.command()
def task(lab_id: str):
    """Print the task text of a lab."""
    typer.echo(render(catalog.get(lab_id).task, get_platform(_settings().platform)))


@app.command()
def validate(paths: list[Path] = typer.Argument(None, help="lab .yaml / .encorlab / folder; default: whole catalog"),
             strict: bool = typer.Option(None, help="require a solution and a 0% blank score (default on for files)")):
    """Validate labs offline: schema, interface names, node limit, solution 100% / starting config 0%."""
    ok = True
    limit = config.from_env().node_limit
    if paths:
        for p in paths:
            try:
                rep = packs.lint(packs.read_dir(p), node_limit=limit, strict=True if strict is None else strict)
            except packs.LabError as e:
                rep = packs.Report(False, None, None, e.errors, e.warnings, [])
            _print_report(rep, str(p))
            ok &= rep.ok
    else:
        for lid, e in catalog.entries().items():
            rep = packs.lint(packs.read_dir(e.path), node_limit=limit, strict=bool(strict),
                             builtin_ids=None if e.source == "builtin" else packs.builtin_ids())
            _print_report(rep, f"[{e.source}] {e.path.name}")
            ok &= rep.ok
    raise typer.Exit(0 if ok else 1)


@app.command()
def pack(source: Path = typer.Argument(..., help="lab folder (lab.yaml [+ solution.cfg, fixtures]) or a lab .yaml"),
         out: Path = typer.Option(None, "-o", "--out", help="output file (default <id>.encorlab)")):
    """Validate strictly and write a shareable .encorlab pack."""
    try:
        pk = packs.read_dir(source)
    except packs.LabError as e:
        for err in e.errors:
            typer.echo(f"ERROR: {err}")
        raise typer.Exit(1)
    rep = packs.lint(pk, node_limit=config.from_env().node_limit, strict=True, builtin_ids=packs.builtin_ids())
    _print_report(rep, str(source))
    if not rep.ok:
        raise typer.Exit(1)
    dest = out or Path(f"{rep.lab_id}{packs.PACK_EXT}")
    dest.write_bytes(packs.build_pack_bytes(pk))
    typer.echo(f"wrote {dest}")


@app.command("import")
def import_lab(file: Path, replace: bool = typer.Option(False, help="overwrite an existing user lab with the same id")):
    """Import a .encorlab pack, a .encorcourse course or a lab .yaml into your user labs folder."""
    data = file.read_bytes()
    if courses.is_course(file.name, data):
        try:
            r = library.install_course_file(data, library.default_url(), node_limit=config.from_env().node_limit, overwrite=replace)
        except (packs.LabError, library.LibraryError) as e:
            for err in getattr(e, "errors", [str(e)]):
                typer.echo(f"ERROR: {err}")
            raise typer.Exit(1)
        for w in r["warnings"]:
            typer.echo(f"warning: {w}")
        typer.echo(f"installed course {r['course_id']}: {r['title']} ({len(r['labs'])} labs, {len(r['installed'])} imported)")
        raise typer.Exit(0)
    try:
        pk = packs.read_upload(file.name, data)
    except packs.LabError as e:
        for err in e.errors:
            typer.echo(f"ERROR: {err}")
        raise typer.Exit(1)
    rep = packs.install(pk, node_limit=config.from_env().node_limit, overwrite=replace)
    _print_report(rep, str(file))
    if rep.ok:
        typer.echo(f"imported {rep.lab_id} -> {catalog.user_labs_dir() / rep.lab_id}")
    raise typer.Exit(0 if rep.ok else 1)


@app.command()
def export(lab_id: str, out: Path = typer.Option(None, "-o", "--out"),
           cml_yaml: bool = typer.Option(False, "--cml-yaml", help="write the CML topology YAML instead of a pack")):
    """Export a lab as a .encorlab pack (or as CML topology YAML)."""
    if cml_yaml:
        s = _settings()
        y = to_yaml(catalog.get(lab_id), get_platform(s.platform), s.lab_prefix)
        if out:
            out.write_text(y, encoding="utf-8")
            typer.echo(f"wrote {out}")
        else:
            typer.echo(y)
        return
    dest = out or Path(f"{lab_id}{packs.PACK_EXT}")
    dest.write_bytes(packs.export_pack(lab_id))
    typer.echo(f"wrote {dest}")


@app.command()
def delete(lab_id: str, yes: bool = typer.Option(False, "--yes", "-y")):
    """Delete an installed lab (your results history is kept; re-installing the lab links it up again)."""
    if not yes and not typer.confirm(f"Delete user lab {lab_id}?"):
        raise typer.Exit(1)
    try:
        packs.delete_user_lab(lab_id)
    except packs.LabError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)
    typer.echo(f"deleted {lab_id}")


@app.command()
def schema(out: Path = typer.Option(None, "-o", "--out")):
    """Print/write the lab JSON Schema."""
    from .prompt import json_schema
    text = json.dumps(json_schema(), indent=2)
    if out:
        out.write_text(text + "\n", encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def prompt(description: str = typer.Argument("", help="what lab you want; empty = template with a placeholder"),
           out: Path = typer.Option(None, "-o", "--out")):
    """Print a self-contained prompt for any AI chatbot to generate a lab."""
    from .prompt import build_prompt
    text = build_prompt(description)
    if out:
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")
    else:
        typer.echo(text)


@app.command()
def docs(out: Path = typer.Option(Path("docs"), "-o", "--out", help="output folder")):
    """Write docs/: AI-PROMPT.md, encorlab-lab.schema.json, LAB-AUTHORING.md, example-lab.yaml."""
    from .prompt import docs_files
    out.mkdir(parents=True, exist_ok=True)
    for name, text in docs_files().items():
        (out / name).write_text(text, encoding="utf-8", newline="\n")
        typer.echo(f"wrote {out / name}")


@app.command()
def doctor():
    """Check connectivity, controller version, console server and node definitions."""
    s = _settings()
    typer.echo(f"Settings: {s!r}")
    info = service.make_cml(s).doctor()
    for k, v in info.items():
        typer.echo(f"{k:28} {v}")
    if not info["version_ok"]:
        typer.echo("WARNING: this build pins virl2_client 2.9.x; controller is not 2.9.x")
    if not info["console_reachable"]:
        typer.echo("NOTE: live console checks unavailable; config mode (HTTPS only) still works. "
                   "A port-22 proxy must be TCP passthrough (nginx stream / HAProxy mode tcp), not HTTP.")
    if info["missing_node_definitions"]:
        raise typer.Exit(1)


@app.command()
def build(lab_id: str, rebuild: bool = typer.Option(False, help="delete and re-import if it exists")):
    """Import + start a lab and wait for boot."""
    service.do_build(_settings(), lab_id, _p, rebuild=rebuild)


def _print_check(rep: dict) -> None:
    for r in rep["results"]:
        typer.echo(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['device']:5} {r['description']}")
        if not r["passed"]:
            for d in r["details"]:
                typer.echo(f"         {d}")
            if r["hint"]:
                typer.echo(f"         hint: {r['hint']}")
    for n in rep["notes"]:
        typer.echo(f"NOTE: {n}")
    typer.echo(f"Mode {rep['mode']}: score {rep['earned']}/{rep['total']} ({rep['score_pct']}%)")
    if rep.get("exam"):
        x = rep["exam"]
        typer.echo("")
        typer.echo(f"EXAM RESULT: {x['final_pct']}%  {'PASS' if x['passed'] else 'FAIL'} (target {x['pass_pct']}%)")
        typer.echo(f"  raw score {x['raw_pct']}%, hints used {x['hints_used']} (-{x['penalty']}), "
                   f"time {_fmt(x['used_s'])} of {_fmt(x['duration_s'])}" + ("  SUBMITTED LATE: scored 0%" if x["late"] else ""))
    if rep.get("fault_fixed"):
        ff = rep["fault_fixed"]
        typer.echo("")
        typer.echo(f"Fault fixed: {ff['title']} (on {ff['device']})")
        typer.echo(ff["explanation"].rstrip())
    if rep.get("passed") and rep.get("solution_summary"):
        typer.echo("")
        typer.echo("Solution summary" + (" (auto-generated)" if rep.get("solution_summary_auto") else "") + ":")
        typer.echo(rep["solution_summary"].rstrip())


@app.command()
def check(lab_id: str, as_json: bool = typer.Option(False, "--json"),
          mode: str = typer.Option(None, help="auto | live | config (default: ENCOR_GRADING_MODE or auto)"),
          hints_used: int = typer.Option(None, "--hints-used", help="record how many hints you used in the history")):
    """Grade a lab (live console checks and/or running-config checks). Prints the solution summary at 100%."""
    rep = service.do_check(_settings(), lab_id, _p, mode=mode, hints_used=hints_used)
    if as_json:
        typer.echo(json.dumps(rep, indent=2))
        return
    _print_check(rep)
    raise typer.Exit(0 if rep["passed"] else 2)


@app.command("step")
def step_cmd(lab_id: str, step: str = typer.Argument(None, help="step id or number (1 = first); omit to list the steps"),
             do_check: bool = typer.Option(False, "--check", help="run this step's checks"),
             do_apply: bool = typer.Option(False, "--apply", help="type this step's config into the devices over the console"),
             yes: bool = typer.Option(False, "--yes", "-y", help="do not ask before --apply")):
    """Walkthrough labs: list the steps, show one step (config + verify commands), check it or apply it."""
    from . import walkthrough
    lab = catalog.get(lab_id)
    if not lab.is_walkthrough:
        typer.echo(f"{lab_id} is not a walkthrough lab", err=True)
        raise typer.Exit(1)
    s = _settings()
    plat = get_platform(s.platform)
    st_all = walkthrough.status(lab)
    if step is None:
        for i, (st, r) in enumerate(zip(lab.steps, st_all["steps"]), 1):
            mark = "PASS" if r["passed"] else ("fail" if r["passed"] is False else "    ")
            typer.echo(f"{i:2}. [{mark}] {st.id:16} {render(st.title, plat)}{'  (optional)' if st.optional else ''}")
        typer.echo(f"Required steps passed: {st_all['required_passed']}/{st_all['required']}"
                   + ("  - completed" if st_all["completed"] else ""))
        return
    st = lab.steps[int(step) - 1] if step.isdigit() and 1 <= int(step) <= len(lab.steps) else lab.step(step)
    if do_check:
        rep = walkthrough.check_step(s, lab_id, st.id, _p, lab=lab)
        _print_check(rep)
        raise typer.Exit(0 if rep["passed"] else 2)
    if do_apply:
        if not yes and not typer.confirm(f"Type the config of step '{st.title}' into {', '.join(st.config)}?"):
            raise typer.Exit(1)
        walkthrough.apply_step(s, lab_id, st.id, _p, lab=lab)
        return
    typer.echo(f"# {render(st.title, plat)}\n\n{render(st.explain, plat).rstrip()}\n")
    for dev, cfg in st.config.items():
        typer.echo(f"! device {dev}\n{render(cfg, plat).rstrip()}\n")
    for v in st.verify:
        typer.echo(f"{v.device}# {render(v.command, plat)}\n    expect: {render(v.expect, plat).strip()}")


@app.command()
def solution(lab_id: str):
    """Print the solution summary (root cause, fix commands per device, why) and the solution config. Spoilers!"""
    from . import exam, solution as sol_mod
    if exam.active(lab_id):
        typer.echo("An exam is running for this lab: the solution is available after you submit (check) or abort it.")
        raise typer.Exit(1)
    lab = catalog.get(lab_id)
    typer.echo(sol_mod.text_report(lab, catalog.load_solution(lab_id), get_platform(config.from_env().platform)))


@app.command()
def hint(lab_id: str, n: int = typer.Argument(1, help="hint number (1 = first, vaguest)")):
    """Print progressive hint N of a lab ('Hint N of M'). During an exam: the next hint, which costs points."""
    from . import exam, solution as sol_mod
    hs = sol_mod.hints(catalog.get(lab_id), get_platform(config.from_env().platform))
    if not hs:
        typer.echo("This lab has no hints.")
        raise typer.Exit(1)
    if exam.active(lab_id):
        try:
            k = exam.use_hint(lab_id, len(hs))
        except exam.ExamError as e:
            typer.echo(f"Exam: {e}")
            raise typer.Exit(1)
        st = exam.status(lab_id)
        typer.echo(f"Hint {k} of {len(hs)} (exam: -{st['penalty']} points each, {k} used): {hs[k - 1]}")
        return
    if not 1 <= n <= len(hs):
        raise typer.BadParameter(f"choose 1..{len(hs)}")
    typer.echo(f"Hint {n} of {len(hs)}: {hs[n - 1]}")


@app.command("test-live")
def test_live(lab_id: str, mode: str = typer.Option("auto"), keep: bool = typer.Option(False, help="keep the test copy")):
    """Build a throw-away copy with the reference solution applied, grade it, delete it."""
    rep = service.do_test_live(_settings(), catalog.get(lab_id), catalog.load_solution(lab_id), _p, mode=mode, keep=keep)
    _print_check(rep)
    raise typer.Exit(0 if rep["passed"] else 2)


@app.command("progress")
def show_progress(as_json: bool = typer.Option(False, "--json")):
    """Progress dashboard: mastery per ENCOR domain, streak, time spent, weakest topics."""
    from . import progress
    p = progress.compute()
    if as_json:
        typer.echo(json.dumps(p, indent=2))
        return
    o, st = p["overall"], p["streak"]
    h, m = divmod(o["time_spent_s"] // 60, 60)
    typer.echo(f"Overall mastery {o['mastery_pct']}% ({p['blueprint']}, weighted by exam domain)")
    typer.echo(f"Labs solved {o['labs_solved']}/{o['labs_total']}, attempted {o['labs_attempted']}, checks {o['checks_run']}, "
               f"faults fixed {o['faults_fixed']}, time {h}h{m:02d}m")
    typer.echo(f"Streak {st['current']} day(s), longest {st['longest']}, active days {st['active_days']}")
    typer.echo("")
    for d in p["domains"]:
        bar = "-" if d["mastery_pct"] is None else "#" * int(d["mastery_pct"] // 10)
        typer.echo(f"{d['id']} {d['name'][:28]:28} {d['weight']:3}%  "
                   + ("no labs yet" if not d["labs"] else f"{d['mastery_pct']:5}% {bar:10} solved {d['solved']}/{d['labs']}"))
    typer.echo("")
    typer.echo("Weakest topics:")
    for i in p["weakest"]:
        typer.echo(f"  {i['id']:6} {i['title'][:40]:40} {i['mastery_pct']}%  labs: {', '.join(i['lab_ids'])}")


@app.command("history")
def show_history(lab_id: str):
    """Show past check results for a lab."""
    for h in history.load(lab_id):
        hu = f"  hints {h['hints_used']}/{h.get('hints_total')}" if h.get("hints_used") is not None else ""
        typer.echo(f"{h['ts']}  {h['mode']:6}  {h['earned']}/{h['total']}{hu}  {'SOLVED' if h['passed'] else ''}")


@app.command("break")
def break_lab(lab_id: str, fault: str = typer.Option(None, help="a specific fault id (default: random)")):
    """Break my lab: rebuild a working lab with one random predefined fault, then troubleshoot it."""
    rep = service.do_break(_settings(), lab_id, _p, fault_id=fault)
    typer.echo("")
    typer.echo("TROUBLE TICKET: " + rep["ticket"])
    typer.echo(f"Fix it, then run: encorlab check {lab_id}   (encorlab fault {lab_id} --reveal to give up)")


@app.command()
def fault(lab_id: str, reveal: bool = typer.Option(False, "--reveal", help="show the cause and fix (spoiler)"),
          end: bool = typer.Option(False, "--end", help="stop fault practice for this lab")):
    """Show the active 'Break my lab' ticket, reveal its answer, or end fault practice."""
    from . import faults
    lab = catalog.get(lab_id)
    plat = get_platform(config.from_env().platform)
    st = faults.active(lab_id)
    if end:
        faults.clear(lab_id)
        typer.echo("fault practice ended (use 'encorlab reset' to go back to the starting configs)")
        return
    if not st:
        typer.echo(f"No active fault. {len(lab.faults)} predefined faults; start with: encorlab break {lab_id}")
        raise typer.Exit(1)
    if reveal:
        faults.mark_revealed(lab_id)
        r = faults.reveal(lab, faults.get(lab, st["fault_id"]), plat)
        typer.echo(f"Fault: {r['title']} (on {r['device']})\n\n{r['explanation'].rstrip()}")
        return
    typer.echo("TROUBLE TICKET: " + faults.public(lab, st, plat)["ticket"])


@app.command("update-check")
def update_check():
    """Check GitHub Releases for a newer version (one anonymous request; nothing is installed)."""
    from . import updates
    try:
        r = updates.check()
    except library.LibraryError as e:
        typer.echo(f"ERROR: could not check for updates: {e}")
        raise typer.Exit(1)
    if r["update_available"]:
        typer.echo(f"Update available: {r['latest']} (you have {r['current']}). Download: {r['url']}")
    else:
        typer.echo(f"You have the latest version ({r['current']}; latest release {r['latest']}).")

    st = updates.status()
    if r["update_available"]:
        if any(a["name"] == updates.patch_name(r["latest"]) for a in r["assets"]):
            typer.echo("A small app patch is available: run `update-install`" if st["patchable"]
                       else f"(App patch available, but {st['reason']})")


@app.command("update-status")
def update_status():
    """Show the running app code, runtime version and installed update (packaged app)."""
    from . import updates
    st = updates.status()
    a = st["active"] or {"version": st["version"], "source": "source tree"}
    typer.echo(f"App code: {a['version']} ({a['source']})   runtime: {st['runtime']}   built-in copy: {st['bundled_version'] or '-'}")
    typer.echo(f"Install type: {st['install_type']}" + (f"   app folder: {st['app_dir']}" if st["app_dir"] else ""))
    if not st["patchable"]:
        typer.echo(f"Patch updates: not available ({st['reason']})")
        return
    typer.echo(f"Installed update: {st['installed'] or '-'}   previous: {st['previous'] or '-'}   pending first start: {st['pending']}")
    if st["failed"]:
        typer.echo(f"Last failed update: {st['failed'].get('version')} ({st['failed'].get('reason')}, {st['failed'].get('at')})")
    if st["restart_needed"]:
        n = st["next_start"]
        typer.echo(f"Restart the app to switch to {n['version']} ({n['source']}).")


@app.command("update-install")
def update_install(file: str = typer.Option("", "--file", help="install a downloaded encorlab-patch-<ver>.zip instead"),
                   sha256: str = typer.Option("", "--sha256", help="expected sha256 of --file (from SHA256SUMS.txt)")):
    """Download, verify and install the latest release's app patch (packaged app). Restart the app afterwards."""
    from . import updates
    try:
        r = updates.install_file(file, sha256 or None) if file else updates.install()
    except (updates.UpdateError, library.LibraryError) as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)
    if r["status"] == "installed":
        typer.echo(f"Installed {r['version']} ({r['size'] / 1024:.0f} KB, sha256 verified). Restart ENCOR Lab Builder to use it.")
    elif r["status"] == "up_to_date":
        typer.echo(f"You have the latest version ({r['current']}).")
    else:
        typer.echo(f"Full download needed: {r['reason']}\n{r['url']}")


@app.command("update-rollback")
def update_rollback():
    """Go back to the previous app code (or the built-in copy) from the next start on (packaged app)."""
    from . import updates
    try:
        r = updates.rollback()
    except updates.UpdateError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)
    n = r["next"]
    typer.echo(f"Rolled back. Next start uses {n['version']} ({n['source']}). Restart ENCOR Lab Builder." if n
               else "Rolled back. Restart ENCOR Lab Builder.")


def _fmt(sec) -> str:
    sec = int(sec or 0)
    return f"{sec // 3600:d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


@app.command("exam")
def exam_cmd(lab_id: str,
             start: bool = typer.Option(False, "--start", help="start a timed exam attempt"),
             minutes: int = typer.Option(0, help="time limit (default depends on the lab)"),
             hints: str = typer.Option("penalty", help="penalty (each hint costs points) or off"),
             penalty: int = typer.Option(10, help="points per hint in penalty mode"),
             abort: bool = typer.Option(False, "--abort", help="abandon the running exam (nothing is recorded)")):
    """Exam mode: timed, one submission (encorlab check), hints off or penalized. Without options: show status."""
    from . import exam
    lab = catalog.get(lab_id)
    if abort:
        exam.clear(lab_id)
        typer.echo("Exam aborted.")
        return
    if start:
        if exam.active(lab_id):
            typer.echo("An exam is already running for this lab (use --abort to abandon it).")
            raise typer.Exit(1)
        try:
            st = exam.start(lab, minutes or None, hints, penalty)
        except exam.ExamError as e:
            typer.echo(f"ERROR: {e}")
            raise typer.Exit(1)
        typer.echo(f"Exam started: {_fmt(st['duration_s'])} on the clock, hints {st['hints']}"
                   + (f" (-{st['penalty']} points each)" if st["hints"] == "penalty" else "") + f", pass target {st['pass_pct']}%.")
        typer.echo(f"Build the lab if needed (encorlab build {lab_id}), solve it, then submit with: encorlab check {lab_id}")
        return
    st = exam.status(lab_id)
    if not st:
        typer.echo(f"No exam running. Start one with: encorlab exam {lab_id} --start [--minutes {exam.default_minutes(lab)}]")
        return
    typer.echo(f"Exam running since {st['started']}: {_fmt(st['remaining_s'])} left of {_fmt(st['duration_s'])}"
               + (" (TIME IS UP - submit now)" if st["expired"] else "") + f", hints {st['hints']}, used {st['hints_used']}.")


@app.command("snapshot")
def snapshot_cmd(lab_id: str,
                 save: str = typer.Option(None, "--save", help="save the running configs under this name ('' = timestamp)"),
                 restore: str = typer.Option(None, "--restore", help="rebuild the lab with this snapshot's configs"),
                 delete: str = typer.Option(None, "--delete", help="delete this snapshot"),
                 show: str = typer.Option(None, "--show", help="print this snapshot's configs"),
                 note: str = typer.Option("", help="note stored with --save"),
                 replace: bool = typer.Option(False, help="overwrite an existing snapshot with --save")):
    """Config snapshots: save / restore / list the running configs of a built lab."""
    from . import snapshots
    catalog.get(lab_id)
    try:
        if save is not None:
            meta = service.do_snapshot_save(_settings(), lab_id, save or snapshots.default_name(), _p, note=note, overwrite=replace)
            typer.echo(f"saved {meta['name']} ({', '.join(meta['nodes'])})")
        elif restore:
            if not typer.confirm(f"Restore {restore!r}? The lab is stopped, wiped and rebooted; current changes are lost."):
                raise typer.Exit(1)
            service.do_snapshot_restore(_settings(), lab_id, restore, _p)
            typer.echo(f"restored {restore}")
        elif delete:
            snapshots.delete(lab_id, delete)
            typer.echo(f"deleted {delete}")
        elif show:
            typer.echo(snapshots.as_cfg(snapshots.load(lab_id, show)), nl=False)
        else:
            items = snapshots.list_snapshots(lab_id)
            if not items:
                typer.echo(f"no snapshots for {lab_id} (save one with: encorlab snapshot {lab_id} --save NAME)")
            for x in items:
                typer.echo(f"{x['name']:<28} {x['created']}  {x['platform'] or '-':<5} {len(x['nodes'])} devices  {x['note']}")
    except snapshots.SnapshotError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)


@app.command("report")
def report_cmd(lab_id: str = typer.Argument(None, help="lab id; omit for the progress report over all labs"),
               out: Path = typer.Option(None, "-o", "--out", help="output .html file"),
               outputs: bool = typer.Option(False, "--outputs", help="include the raw command output of each check"),
               name: str = typer.Option("", "--name", help="your name, printed in the report header")):
    """Write a printable HTML report (open it in a browser and print / save as PDF)."""
    from . import report
    html = report.lab_report(lab_id, outputs=outputs, student=name) if lab_id else report.progress_report(student=name)
    out = out or Path(f"encor-report-{lab_id or 'progress'}.html")
    out.write_text(html, encoding="utf-8")
    typer.echo(f"wrote {out} (open it in a browser and print, or save as PDF)")


@app.command("console")
def console_cmds(lab_id: str):
    """Show the CML web link and console server commands for the lab's nodes."""
    s = _settings()
    st = service.do_status(s, lab_id)
    if not st.get("exists"):
        typer.echo(f"{lab_id} is not built in CML yet (run: encorlab build {lab_id})")
        raise typer.Exit(1)
    if st.get("cml_lab_url"):
        typer.echo(f"CML web UI: {st['cml_lab_url']}")
    for c in st["consoles"]:
        typer.echo(f"{c['node']:<8} {(c['state'] or '-'):<9} {c['ssh']}")


@app.command()
def reset(lab_id: str):
    """Stop, wipe, restore initial configs and restart a lab (during fault practice: the broken configs)."""
    service.do_reset(_settings(), lab_id, _p)


@app.command()
def destroy(lab_id: str):
    """Stop, wipe and delete a lab from CML."""
    service.do_destroy(_settings(), lab_id, _p)


@app.command("save-password")
def save_password():
    """Store the CML password in the OS keyring (Windows Credential Manager / Secret Service)."""
    s = config.from_env()
    user = s.username or typer.prompt("CML username")
    pw = typer.prompt("CML password", hide_input=True)
    typer.echo("saved" if config.keyring_set(user, pw) else "keyring not available on this system")


@app.command()
def web(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = typer.Option(True, "--open/--no-open")):
    """Start the local web UI (http://127.0.0.1:8765)."""
    import threading
    import uvicorn
    import webbrowser
    from .web.app import create_app
    if host not in ("127.0.0.1", "localhost", "::1"):
        typer.echo("WARNING: binding to a non-loopback address exposes the UI to your network")
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{port}"
    typer.echo(f"ENCOR Lab Builder {__version__} on {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")



# ---------------------------------------------------------------- courses + online library
course_app = typer.Typer(help="Courses: ordered bundles of labs (.encorcourse).", no_args_is_help=True)
library_app = typer.Typer(help="Online lab library (packs and courses from the GitHub repo or a URL).", no_args_is_help=True)
app.add_typer(course_app, name="course")
app.add_typer(library_app, name="library")


def _best() -> dict:
    from . import walkthrough
    out = {}
    for lid, e in catalog.entries().items():
        if e.lab.is_walkthrough:
            out[lid] = 100.0 if walkthrough.status(e.lab)["completed"] else None
        else:
            out[lid] = max((x.get("score_pct") or 0 for x in history.load(lid)), default=None)
    return out


@course_app.command("list")
def course_list():
    """Installed courses with your progress."""
    st = config.from_env()
    cs = courses.list_courses(_best(), platform=st.platform, heavy_gb=st.ram_heavy_gb)
    if not cs:
        typer.echo("no courses installed (import a .encorcourse file, or: encorlab library list)")
    for c in cs:
        typer.echo(f"{c['id']}: {c['title']}  [{c['solved']}/{c['total']} solved]" + (f"  next: {c['next']}" if c["next"] else ""))
        for i, l in enumerate(c["labs"], 1):
            st = "solved" if l["solved"] else (f"best {l['best']:g}%" if l["best"] is not None else ("missing" if not l["available"] else "-"))
            typer.echo(f"   {i}. {l['id']:<28} {st:<10} {l['title']}")


@course_app.command("build")
def course_build(source: Path = typer.Argument(..., help="folder with course.yaml (+ labs/<id>/ folders)"),
                 out: Path = typer.Option(None, "-o", "--out"),
                 search: list[Path] = typer.Option(None, "--labs-from", help="also take listed labs from <dir>/<id>/")):
    """Build and validate a .encorcourse file."""
    try:
        data = courses.build(source, search=search or [])
    except packs.LabError as e:
        for err in e.errors:
            typer.echo(f"ERROR: {err}")
        raise typer.Exit(1)
    c = courses.parse_course_yaml((source / "course.yaml").read_text(encoding="utf-8"))
    out = out or Path(f"{c.id}{courses.COURSE_EXT}")
    out.write_bytes(data)
    typer.echo(f"wrote {out} ({len(data)} bytes, sha256 {library.sha256(data)})")


@course_app.command("delete")
def course_delete(course_id: str, labs: bool = typer.Option(False, "--labs", help="also delete its imported labs")):
    """Remove an installed course (built-in labs are never deleted)."""
    try:
        removed = courses.delete(course_id, remove_labs=labs)
    except packs.LabError as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)
    typer.echo(f"removed course {course_id}" + (f" and labs: {', '.join(removed)}" if removed else ""))


_URL_HELP = "library index URL (default: Settings > Library URL, else the project's GitHub repo)"


@library_app.command("list")
def library_list(url: str = typer.Option("", help=_URL_HELP)):
    """Show what the online library offers (RAM estimate, size, installed / update available)."""
    st = config.from_env()
    try:
        idx = library.index(url or library.default_url(), heavy_gb=st.ram_heavy_gb)
    except (library.LibraryError, packs.LabError) as e:
        typer.echo(f"ERROR: {e}")
        raise typer.Exit(1)
    for it in idx["items"]:
        mark = "update" if it.get("update_available") else ("installed" if it["installed"] else "")
        ram = ""
        if it.get("ram_gb"):
            ram = ("RAM heavy " if it.get("ram_heavy") else "") + f"~{it['ram_gb']:g} GB"
        star = " *" if it.get("starter") else ""
        typer.echo(f"{it['file']:<36} {it['kind']:<6} {mark:<9} {ram:>16} {it['size'] / 1024:6.1f} KB  {it['title']}{star}")
    if idx.get("starter"):
        typer.echo("* = recommended starter set (encorlab library install --starter)")


@library_app.command("install")
def library_install(target: str = typer.Argument(None, help="a file name from 'library list', or an https URL"),
                    sha256: str = typer.Option("", help="expected sha256 (recommended for URLs)"),
                    url: str = typer.Option("", help=_URL_HELP),
                    replace: bool = typer.Option(False, help="overwrite existing imported labs"),
                    starter: bool = typer.Option(False, "--starter", help="install the recommended starter set"),
                    all_labs: bool = typer.Option(False, "--all", help="install every lab in the library"),
                    updates: bool = typer.Option(False, "--updates", help="update installed labs that have a newer version")):
    """Download, verify (sha256) and install a pack or course (a course also installs the labs it lists)."""
    lim = config.from_env().node_limit
    url = url or library.default_url()
    if starter or all_labs or updates:
        try:
            ids = [i["id"] for i in library.parse_index(library.http_fetch(url, library.MAX_INDEX_BYTES))
                   if i["kind"] == "lab"] if all_labs else []
            r = library.install_many(ids, starter=starter, updates=updates, url=url, node_limit=lim)
        except (library.LibraryError, packs.LabError) as e:
            typer.echo(f"ERROR: {e}")
            raise typer.Exit(1)
        typer.echo(f"installed: {', '.join(r['installed']) or '-'}")
        if r["skipped"]:
            typer.echo(f"already installed: {', '.join(r['skipped'])}")
        for k, v in r["failed"].items():
            typer.echo(f"ERROR: {k}: {v}")
        raise typer.Exit(0 if r["ok"] else 1)
    if not target:
        typer.echo("ERROR: give a file name or URL, or --starter / --all / --updates")
        raise typer.Exit(2)
    try:
        if target.startswith(("https://", "http://")):
            r = library.install_url(target, sha256, node_limit=lim, overwrite=replace)
        else:
            r = library.install_item(target, url=url, node_limit=lim, overwrite=replace)
    except (library.LibraryError, packs.LabError) as e:
        for err in getattr(e, "errors", [str(e)]):
            typer.echo(f"ERROR: {err}")
        raise typer.Exit(1)
    for w in r.get("warnings", []):
        typer.echo(f"warning: {w}")
    what = f"course {r['course_id']}" if r.get("kind") == "course" else f"lab {r['lab_id']}"
    typer.echo(f"installed {what}: {r['title']}" + ("" if r.get("verified", True) else " (no sha256 given: integrity not verified)"))
    if r.get("from_library"):
        typer.echo(f"also installed from the library: {', '.join(r['from_library'])}")


@library_app.command("restore")
def library_restore(url: str = typer.Option("", help=_URL_HELP)):
    """Install the labs your previous version bundled that could not be copied from disk (after an update)."""
    from . import migrate
    st = migrate.restore(url or library.default_url(), node_limit=config.from_env().node_limit)
    if st["state"] != "pending":
        typer.echo("nothing to restore" + (f" (restored: {', '.join(st['restored'])})" if st["restored"] else ""))
        return
    typer.echo(f"still missing: {', '.join(st['pending'])}" + (f"\nERROR: {st['last_error']}" if st["last_error"] else ""))
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
