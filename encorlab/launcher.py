"""Desktop launcher (entry point of the packaged ENCORLab / ENCORLab.exe build).

    ENCORLab                     start the web UI on http://127.0.0.1:8765 (next free port if busy)
                                 and open the default browser; close the window / Ctrl+C to quit
    ENCORLab --port 9000         preferred port
    ENCORLab --no-browser        don't open a browser
    ENCORLab --restarted         (used by "Restart now" after an update: open a browser only if the port changed)
    ENCORLab <command> [...]     run a CLI command instead, e.g. `ENCORLab list`, `ENCORLab check eigrp-basic`

If the app is already running on the preferred port, the launcher just opens the browser there.
User data (settings.json, imported labs, history) stays in %APPDATA%\\cml-lab-builder or ~/.config/cml-lab-builder;
nothing is written next to the executable."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

DEFAULT_PORT = 8765
HOST = "127.0.0.1"   # loopback only, always
_SERVER = None        # the running uvicorn.Server (set by serve())
_RESTART = False      # set by request_restart(): start a fresh process once the server has stopped


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _running_instance(port: int) -> str | None:
    """Version string if CML Lab Builder already answers on this port."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/health", timeout=1.5) as r:
            data = json.loads(r.read().decode("utf-8"))
        return str(data.get("version")) if data.get("ok") else None
    except Exception:
        return None


def bind_socket(preferred: int = DEFAULT_PORT, span: int = 30) -> socket.socket:
    """Listening socket on 127.0.0.1: preferred port, else the next free one, else any free port."""
    for port in [preferred, *range(preferred + 1, preferred + span), 0]:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name != "nt":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        else:  # never share a port with another process on Windows
            s.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
        try:
            s.bind((HOST, port))
            s.listen(128)
            return s
        except OSError:
            s.close()
    raise OSError("no free TCP port on 127.0.0.1")


def _parse(argv: list[str]) -> tuple[dict, list[str] | None]:
    opts = {"port": DEFAULT_PORT, "browser": True}
    rest = list(argv)
    while rest and rest[0].startswith("--"):
        a = rest.pop(0)
        if a == "--no-browser":
            opts["browser"] = False
        elif a == "--restarted":
            opts["restarted"] = True
        elif a == "--port" and rest:
            opts["port"] = int(rest.pop(0))
        elif a.startswith("--port="):
            opts["port"] = int(a.split("=", 1)[1])
        elif a in ("-h", "--help"):
            return opts, ["--help"]
        else:
            return opts, [a, *rest]
    return opts, (rest or None)


def can_restart() -> bool:
    """Restart now is offered in the packaged app (from source, just start run.bat / run.sh again)."""
    return frozen() and _SERVER is not None


def request_restart() -> None:
    """Stop the web server; serve() then starts a fresh copy of the app on the same port (which re-runs the boot
    loader, so an installed update or a rollback takes effect)."""
    global _RESTART
    if not can_restart():
        raise RuntimeError("restart is only available in the packaged app; close it and start it again")
    _RESTART = True
    threading.Timer(0.4, lambda: setattr(_SERVER, "should_exit", True)).start()


def _respawn(port: int) -> None:
    args = [sys.executable, "--restarted", "--port", str(port)]
    print("Restarting CML Lab Builder...", flush=True)
    if os.name == "nt":   # a new console window becomes the "quit" control; this one closes
        subprocess.Popen(args, creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x10), close_fds=True)
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, args)   # same terminal, same PID


def _mark_good() -> None:
    """Tell the boot loader the (possibly freshly patched) app code reached a working web UI."""
    try:
        import encorboot
        encorboot.mark_good()
    except Exception:
        pass


def serve(port: int = DEFAULT_PORT, browser: bool = True, ready: threading.Event | None = None,
          restarted: bool = False) -> int:
    import uvicorn
    from . import __version__
    from .config import settings_file
    from .web.app import create_app

    other = _running_instance(port)
    if other:
        url = f"http://{HOST}:{port}/"
        print(f"CML Lab Builder {other} is already running at {url} - opening it.")
        if browser:
            webbrowser.open(url)
        return 0
    global _SERVER, _RESTART
    sock = None
    for _ in range(40 if restarted else 1):   # after a restart the old process may need a moment to let go
        sock = bind_socket(port, span=1 if restarted else 30)
        if sock.getsockname()[1] == port or not restarted:
            break
        sock.close()
        time.sleep(0.25)
    if restarted and sock.getsockname()[1] != port:
        sock = bind_socket(port)
    real = sock.getsockname()[1]
    url = f"http://{HOST}:{real}/"
    if restarted:
        browser = real != port   # the open tab reconnects by itself unless the port changed
    server = uvicorn.Server(uvicorn.Config(create_app(auto_update=True), log_level="warning", lifespan="off"))
    _SERVER, _RESTART = server, False

    def _when_up():
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        if server.started:
            _mark_good()
        if ready is not None:
            ready.set()
        if browser:
            webbrowser.open(url)

    print("=" * 64)
    print(f" CML Lab Builder {__version__}")
    print(f" Web UI:    {url}" + ("" if real == port else f"   (port {port} was busy)"))
    print(f" Your data: {settings_file().parent}")
    print(" Keep this window open while you use the app.")
    print(" To quit: close this window or press Ctrl+C.")
    print("=" * 64, flush=True)
    threading.Thread(target=_when_up, daemon=True).start()
    try:
        server.run(sockets=[sock])
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
        _SERVER = None
    if _RESTART:
        _RESTART = False
        _respawn(real)
        return 0
    print("CML Lab Builder stopped.")
    return 0


def _fatal(exc: BaseException) -> int:
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        from .config import settings_file
        log = settings_file().parent / "launcher-error.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(text, encoding="utf-8")
        where = f"\nDetails were saved to {log}"
    except Exception:
        where = ""
    print("\nCML Lab Builder could not start:\n" + text + where, file=sys.stderr)
    if frozen() and os.name == "nt" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    return 1


def _console_title() -> None:
    """The console window shows the product name (Windows; a terminal title escape elsewhere when interactive)."""
    try:
        if os.name == "nt":
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("CML Lab Builder")
        elif sys.stdout.isatty():
            sys.stdout.write("\033]0;CML Lab Builder\007")
            sys.stdout.flush()
    except Exception:  # noqa: BLE001 - cosmetic
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    opts, cli_args = _parse(argv)
    if cli_args is not None:
        from .cli import app
        try:
            app(args=cli_args, prog_name="ENCORLab", standalone_mode=True)
        except SystemExit as e:
            return int(e.code or 0) if not isinstance(e.code, str) else 1
        return 0
    _console_title()
    try:
        return serve(opts["port"], opts["browser"], restarted=bool(opts.get("restarted")))
    except Exception as e:  # pragma: no cover - shown to the user in the console window
        return _fatal(e)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
