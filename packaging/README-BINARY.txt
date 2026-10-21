CML Lab Builder - ready-to-run build
======================================

No Python and no install needed. Your settings, imported labs and history are kept in
  Windows: %APPDATA%\cml-lab-builder\   Linux: ~/.config/cml-lab-builder/
(an older ENCOR Lab Builder folder, encorlab, is copied there on the first start and left as it was)
so you can replace this folder with a newer version at any time without losing anything.

START
  Windows: double-click CMLLabBuilder.exe
  Linux:   ./cml-lab-builder (optional: ./install-desktop-entry.sh adds a menu entry)

A small console window opens and your browser shows the app at http://127.0.0.1:8765
(the next free port is used if 8765 is busy; the window shows the real address).
Starting it again while it runs just opens the browser on the running copy.
QUIT: close the console window or press Ctrl+C in it.

LABS
  The download contains no labs (that keeps it small). On the first start the Labs page offers
  "Install recommended starter set" and "Browse library": labs are downloaded from the online
  lab library (sha256-checked) into your user folder. You can also import a .cmllab file
  (or an older .encorlab file).
  Updating from 1.x keeps all your labs, history and progress (the labs 1.x bundled are copied
  into your user folder on the first start).

COMMAND LINE
  cml-lab-builder --port 9000 | --no-browser       launcher options (CMLLabBuilder.exe on Windows)
  cml-lab-builder list | check <lab> | validate ... any CLI command from README.md

WINDOWS SMARTSCREEN
  The exe is not code-signed, so the first start may show "Windows protected your PC".
  Click "More info" -> "Run anyway". If the zip came from the internet you can also
  right-click the zip -> Properties -> Unblock before extracting.

FILES
  docs/            lab authoring guide, AI prompt, JSON Schema
  _internal/       the bundled Python runtime and app files (don't move files out of it)
  LICENSE.txt      CML Lab Builder is MIT-licensed (Copyright (c) 2026 Dylan Vaughan (Specops13))
  THIRD-PARTY-NOTICES.txt  licenses of the bundled Python runtime and packages (paramiko: LGPL-2.1, ...)
