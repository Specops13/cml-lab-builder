"""Command line interface: encorlab <command>  (or python -m encorlab <command>)."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__, catalog, config, history, packs, service
from .platforms import get as get_platform, render
from .render import to_yaml

app = typer.Typer(add_completion=False, help=f"ENCOR Lab Builder {__version__}: build CCNP ENCOR labs in CML 2.9 and grade them.")


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
    """List the lab catalog (built-in and imported)."""
    plat = get_platform(config.from_env().platform)
    for lid, e in catalog.entries().items():
        lab = e.lab
        typer.echo(f"{lid:28} {e.source:7} {lab.node_count} nodes  d{lab.difficulty}  [{', '.join(lab.blueprint)}]  {render(lab.title, plat)}")


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
    """Import a .encorlab pack or lab .yaml into your user labs folder."""
    try:
        pk = packs.read_upload(file.name, file.read_bytes())
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
    """Delete an imported (user) lab."""
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


@app.command()
def solution(lab_id: str):
    """Print the solution summary (root cause, fix commands per device, why) and the solution config. Spoilers!"""
    from . import solution as sol_mod
    lab = catalog.get(lab_id)
    typer.echo(sol_mod.text_report(lab, catalog.load_solution(lab_id), get_platform(config.from_env().platform)))


@app.command()
def hint(lab_id: str, n: int = typer.Argument(1, help="hint number (1 = first, vaguest)")):
    """Print progressive hint N of a lab ('Hint N of M')."""
    from . import solution as sol_mod
    hs = sol_mod.hints(catalog.get(lab_id), get_platform(config.from_env().platform))
    if not hs:
        typer.echo("This lab has no hints.")
        raise typer.Exit(1)
    if not 1 <= n <= len(hs):
        raise typer.BadParameter(f"choose 1..{len(hs)}")
    typer.echo(f"Hint {n} of {len(hs)}: {hs[n - 1]}")


@app.command("test-live")
def test_live(lab_id: str, mode: str = typer.Option("auto"), keep: bool = typer.Option(False, help="keep the test copy")):
    """Build a throw-away copy with the reference solution applied, grade it, delete it."""
    rep = service.do_test_live(_settings(), catalog.get(lab_id), catalog.load_solution(lab_id), _p, mode=mode, keep=keep)
    _print_check(rep)
    raise typer.Exit(0 if rep["passed"] else 2)


@app.command("history")
def show_history(lab_id: str):
    """Show past check results for a lab."""
    for h in history.load(lab_id):
        hu = f"  hints {h['hints_used']}/{h.get('hints_total')}" if h.get("hints_used") is not None else ""
        typer.echo(f"{h['ts']}  {h['mode']:6}  {h['earned']}/{h['total']}{hu}  {'SOLVED' if h['passed'] else ''}")


@app.command()
def reset(lab_id: str):
    """Stop, wipe, restore initial configs and restart a lab."""
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


if __name__ == "__main__":
    app()
