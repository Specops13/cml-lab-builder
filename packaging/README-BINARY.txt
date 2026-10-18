ENCOR Lab Builder - ready-to-run build
======================================

No Python and no install needed. Your settings, imported labs and history are kept in
  Windows: %APPDATA%\encorlab\        Linux: ~/.config/encorlab/
so you can replace this folder with a newer version at any time without losing anything.

START
  Windows: double-click ENCORLab.exe
  Linux:   ./ENCORLab        (optional: ./install-desktop-entry.sh adds a menu entry)

A small console window opens and your browser shows the app at http://127.0.0.1:8765
(the next free port is used if 8765 is busy; the window shows the real address).
Starting it again while it runs just opens the browser on the running copy.
QUIT: close the console window or press Ctrl+C in it.

COMMAND LINE
  ENCORLab --port 9000 | --no-browser       launcher options
  ENCORLab list | check <lab> | validate ... any CLI command from README.md

WINDOWS SMARTSCREEN
  The exe is not code-signed, so the first start may show "Windows protected your PC".
  Click "More info" -> "Run anyway". If the zip came from the internet you can also
  right-click the zip -> Properties -> Unblock before extracting.

FILES
  example-packs/   importable .encorlab packs (drag onto the Labs page)
  docs/            lab authoring guide, AI prompt, JSON Schema
  _internal/       the bundled Python runtime and app files (don't move files out of it)
