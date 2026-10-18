#!/usr/bin/env bash
# Adds "ENCOR Lab Builder" to your desktop menu (per user, no sudo). Run it from the unpacked folder.
# Re-run it if you move the folder. Remove: rm ~/.local/share/applications/encorlab.desktop
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/encorlab.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=ENCOR Lab Builder
Comment=Build and grade CCNP ENCOR labs in Cisco Modeling Labs
Exec="$HERE/ENCORLab"
Icon=$HERE/_internal/encorlab.png
Terminal=true
Categories=Education;Network;
DESK
echo "Added ENCOR Lab Builder to your applications menu."
