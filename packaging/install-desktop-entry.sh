#!/usr/bin/env bash
# Adds "CML Lab Builder" to your desktop menu (per user, no sudo). Run it from the unpacked folder.
# Re-run it if you move the folder. Remove: rm ~/.local/share/applications/cml-lab-builder.desktop
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/cml-lab-builder.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=CML Lab Builder
Comment=Build and grade hands-on labs in Cisco Modeling Labs
Exec="$HERE/cml-lab-builder"
Icon=$HERE/_internal/cml-lab-builder.png
Terminal=true
Categories=Education;Network;
DESK
echo "Added CML Lab Builder to your applications menu."
