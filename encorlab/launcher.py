"""Desktop launcher (entry point of the packaged ENCORLab / ENCORLab.exe build).

    ENCORLab                     start the web UI on http://127.0.0.1:8765 (next free port if busy)
                                 and open the default browser; close the window / Ctrl+C to quit
    ENCORLab --port 9000         preferred port
    ENCORLab --no-browser        don't open a browser
    ENCORLab <command> [...]     run a CLI command instead, e.g. `ENCORLab list`, `ENCORLab check eigrp-basic`

If the app is already running on the preferred port, the launcher just opens the browser there.
User data (settings.json, imported labs, history) stays in %APPDATA%\\encorlab or ~/.config/encorlab;
nothing is written next to the executable."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

DEFAULT_PORT = 8765
HOST = "127.0.0.1"   # loopback only, always


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _running_instance(port: int) -> str | None:
    """Version string if ENCOR Lab Builder already answers on this port."""
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
        elif a == "--port" and rest:
            opts["port"] = int(rest.pop(0))
        elif a.startswith("--port="):
            opts["port"] = int(a.split("=", 1)[1])
        elif a in ("-h", "--help"):
            return opts, ["--help"]
        else:
            return opts, [a, *rest]
    return opts, (rest or None)


def serve(port: int = DEFAULT_PORT, browser: bool = True, ready: threading.Event | None = None) -> int:
    import uvicorn
    from . import __version__
    from .config import settings_file
    from .web.app import create_app

    other = _running_instance(port)
    if other:
        url = f"http://{HOST}:{port}/"
        print(f"ENCOR Lab Builder {other} is already running at {url} - opening it.")
        if browser:
            webbrowser.open(url)
        return 0
    sock = bind_socket(port)
    real = sock.getsockname()[1]
    url = f"http://{HOST}:{real}/"
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning", lifespan="off"))

    def _when_up():
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        if ready is not None:
            ready.set()
        if browser:
            webbrowser.open(url)

    print("=" * 64)
    print(f" ENCOR Lab Builder {__version__}")
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
    print("ENCOR Lab Builder stopped.")
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
    print("\nENCOR Lab Builder could not start:\n" + text + where, file=sys.stderr)
    if frozen() and os.name == "nt" and sys.stdin and sys.stdin.isatty():
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    return 1


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
    try:
        return serve(opts["port"], opts["browser"])
    except Exception as e:  # pragma: no cover - shown to the user in the console window
        return _fatal(e)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
