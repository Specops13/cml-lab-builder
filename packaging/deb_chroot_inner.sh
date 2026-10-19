#!/bin/bash
# Runs inside the chroot (see deb_chroot_test.sh). Packages are in /tmp/debtest, the repo at /src (read-only).
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
FAILS=0; D=/tmp/debtest; U=tester; H=/home/$U; DATA=$H/.config/encorlab
ok()   { echo "PASS $*"; }
bad()  { echo "FAIL $*"; FAILS=$((FAILS+1)); }
chk()  { local msg=$1; shift; local o; if o=$("$@" 2>&1); then ok "$msg"; else bad "$msg"; echo "$o" | sed 's/^/   /' | head; fi; }
as()   { su "$U" -s /bin/bash -c "cd $H && $*"; }
appver() { as "encorlab version" 2>/dev/null | tail -1 | awk '{print $NF}'; }

dpkg -s encorlab >/dev/null 2>&1 && { apt-get purge -y encorlab >/dev/null; }
id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash "$U"
rm -rf "$H/.config"

echo "== install $D/encorlab_${VER}_amd64.deb"
apt-get update -qq
apt-get install -y "$D/encorlab_${VER}_amd64.deb" > /tmp/apt-install.log 2>&1 && ok "apt install ./encorlab_${VER}_amd64.deb (deps resolved)" || { bad "apt install"; tail -20 /tmp/apt-install.log; }
grep -E "^(Setting up|Unpacking) " /tmp/apt-install.log | sed 's/^/   /' | head -20
apt-get install -y -qq python3 desktop-file-utils procps >/tmp/apt-tools.log 2>&1 || { bad "test tools"; tail /tmp/apt-tools.log; }
chk "/usr/bin/encorlab is executable" test -x /usr/bin/encorlab
chk "/opt/encorlab/install-type says deb" grep -qx deb /opt/encorlab/install-type
chk "desktop-file-validate" desktop-file-validate /usr/share/applications/encorlab.desktop
chk "hicolor icons installed" test -f /usr/share/icons/hicolor/256x256/apps/encorlab.png -a -f /usr/share/icons/hicolor/48x48/apps/encorlab.png
chk "man page installed" test -f /usr/share/man/man1/encorlab.1.gz
chk "dpkg --verify clean after install" test -z "$(dpkg --verify encorlab)"
v=$(appver); [ "$v" = "$VER" ] && ok "encorlab version as $U -> $v" || bad "encorlab version -> $v"
as "encorlab update-status" | sed 's/^/   /'
as "encorlab update-status" | grep -q "Install type: deb" && ok "update-status reports install type deb" || bad "install type"

echo "== launch like the menu entry"
EXEC=$(sed -n 's/^Exec=//p' /usr/share/applications/encorlab.desktop)
printf '#!/bin/sh\necho "$1" >> /tmp/browser.log\n' > /tmp/fakebrowser; chmod 755 /tmp/fakebrowser; rm -f /tmp/browser.log
as "BROWSER=/tmp/fakebrowser nohup $EXEC > /tmp/launch1.log 2>&1 &"
up=0; for i in $(seq 60); do python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=1)" 2>/dev/null && { up=1; break; }; sleep 0.5; done
[ $up = 1 ] && ok "menu launch ($EXEC) starts the server on 127.0.0.1:8765" || { bad "server did not start"; cat /tmp/launch1.log; }
for i in $(seq 20); do [ -s /tmp/browser.log ] && break; sleep 0.25; done
grep -q "http://127.0.0.1:8765" /tmp/browser.log 2>/dev/null && ok "browser opened at $(head -1 /tmp/browser.log)" || bad "browser not opened"
n1=$(pgrep -c -f '^/opt/encorlab/ENCORLab') || true
out=$(as "BROWSER=/tmp/fakebrowser timeout 20 $EXEC" 2>&1); rc=$?
echo "   second launch: $(echo "$out" | tail -2 | tr '\n' ' ')"
[ $rc = 0 ] && echo "$out" | grep -qi "already running" && ok "second launch exits and reuses the running app" || bad "second launch rc=$rc"
[ "$(wc -l < /tmp/browser.log)" = 2 ] && ok "second launch only opened the browser again" || bad "browser log: $(cat /tmp/browser.log)"
n2=$(pgrep -c -f '^/opt/encorlab/ENCORLab') || true
[ "$n1" = "$n2" ] && ok "still one app instance ($n2 process(es))" || bad "processes $n1 -> $n2"
python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8766/api/health',timeout=1)" 2>/dev/null && bad "a second server on 8766" || ok "no second server on the next port"
pkill -f '^/opt/encorlab/ENCORLab'; sleep 1

echo "== smoke test of the installed package as $U (patches + auto-update against a fake release)"
find /opt/encorlab -printf '%p %s %m\n' | sort > /tmp/opt.before
PACKS=$(ls /opt/encorlab/example-packs/*.encorlab | sed 's/^/--pack /' | tr '\n' ' ')
as "python3 /src/packaging/smoke_test.py /usr/bin/encorlab --version $VER --data-dir $DATA --patch-test --auto-update-test $PACKS" > /tmp/smoke.log 2>&1; rc=$?
grep -E "^(PASS|FAIL)" /tmp/smoke.log | sed 's/^/   /'
[ $rc = 0 ] && ok "smoke test passed ($(grep -c ^PASS /tmp/smoke.log) checks)" || { bad "smoke test rc=$rc"; tail -30 /tmp/smoke.log; }
find /opt/encorlab -printf '%p %s %m\n' | sort > /tmp/opt.after
chk "/opt/encorlab untouched by patch installs" cmp /tmp/opt.before /tmp/opt.after
chk "dpkg --verify clean after patching" test -z "$(dpkg --verify encorlab)"

echo "== upgrades: user patch 1.8.5 vs newer debs"
rm -rf "$DATA/app" "$DATA/updates"
as "encorlab update-install --file $D/user-patch-1.8.5.zip" | tail -1 | sed 's/^/   /'
v=$(appver); [ "$v" = 1.8.5 ] && ok "user patch 1.8.5 runs over deb $VER" || bad "after patch -> $v"
apt-get install -y "$D/encorlab_1.8.1_amd64.deb" > /tmp/apt-up1.log 2>&1 && ok "apt install ./encorlab_1.8.1_amd64.deb over $VER" || { bad "upgrade to 1.8.1"; tail /tmp/apt-up1.log; }
chk "dpkg --verify clean after upgrade" test -z "$(dpkg --verify encorlab)"
[ "$(dpkg-query -W -f='${Version}' encorlab)" = 1.8.1 ] && ok "dpkg now has 1.8.1"
v=$(appver); [ "$v" = 1.8.5 ] && ok "newer user patch 1.8.5 keeps winning over bundled 1.8.1" || bad "after 1.8.1 deb -> $v"
apt-get install -y "$D/encorlab_1.9.0_amd64.deb" > /tmp/apt-up2.log 2>&1 && ok "apt install ./encorlab_1.9.0_amd64.deb over 1.8.1" || bad "upgrade to 1.9.0"
v=$(appver); [ "$v" = 1.9.0 ] && ok "newer bundled 1.9.0 beats the 1.8.5 patch" || bad "after 1.9.0 deb -> $v"
chk "user data dir untouched by upgrades" test -d "$DATA/app/1.8.5" -a -d "$DATA/labs/ospf-multiarea-stub"

echo "== remove / purge"
apt-get remove -y encorlab > /tmp/apt-rm.log 2>&1 && ok "apt remove encorlab" || bad "apt remove"
chk "/opt/encorlab gone after remove" test ! -e /opt/encorlab
chk "/usr/bin/encorlab gone after remove" test ! -e /usr/bin/encorlab
chk "menu entry gone after remove" test ! -e /usr/share/applications/encorlab.desktop
chk "~/.config/encorlab kept after remove" test -d "$DATA/labs/ospf-multiarea-stub"
apt-get purge -y encorlab > /tmp/apt-purge.log 2>&1 && ok "apt purge encorlab" || bad "apt purge"
grep -i "kept" /tmp/apt-purge.log | sed 's/^/   /'
chk "package fully gone from dpkg" test -z "$(dpkg -l encorlab 2>/dev/null | grep -E '^(ii|rc)')"
chk "~/.config/encorlab kept after purge" test -d "$DATA/labs/ospf-multiarea-stub" -a -d "$DATA/app/1.8.5"

echo; [ $FAILS = 0 ] && echo "DEB CHROOT TEST PASSED" || { echo "DEB CHROOT TEST FAILED ($FAILS)"; exit 1; }
