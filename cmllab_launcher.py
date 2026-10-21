"""PyInstaller entry script (kept outside the package so relative imports work).

The packaged build loads the app code through cmlboot: the newest valid bundle (an installed patch in the user
data folder, or the copy bundled in _internal/appcode) is imported, with automatic rollback if a fresh patch fails
before the web UI starts. Running from source, this simply runs the cmllab package."""
import multiprocessing
import sys


def run(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    import cmlboot
    if not cmlboot.frozen():
        from cmllab.launcher import main
        return main(argv)
    gui = cmlboot.is_gui(argv)
    while True:
        try:
            cmlboot.activate(gui=gui)
        except RuntimeError as e:
            print(f"CML Lab Builder could not start: {e}", file=sys.stderr)
            return 1
        try:
            from cmllab.launcher import main
            code = main(argv)
        except Exception as e:  # app code broken after import
            code, err = 1, f"{type(e).__name__}: {e}"
        else:
            err = f"exited with code {code}"
        if code and gui and cmlboot.pending_active():
            print(f"\nThe update {cmlboot.ACTIVE.version} failed to start ({err}); rolling back.", file=sys.stderr)
            if cmlboot.fail_active(f"{err} before the web UI started"):
                continue
        return int(code or 0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(run())
