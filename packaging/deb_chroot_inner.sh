#!/bin/bash
# Runs inside the chroot (see deb_chroot_test.sh). Packages are in /tmp/debtest, the repo at /src (read-only).
set -uo pipefail
export DEBIAN_FRONTEND=noninteractive LC_ALL=C.UTF-8
FAILS=0; D=/tmp/debtest; U=tester; H=/home/$U; DATA=$H/.config/cml-lab-builder   # data and app updates (3.0.0+)
P=cml-lab-builder; DEB=$D/${P}_${VER}_amd64.deb
ok()   { echo "PASS $*"; }
bad()  { echo "FAIL $*"; FAILS=$((FAILS+1)); }
chk()  { local msg=$1; shift; local o; if o=$("$@" 2>&1); then ok "$msg"; else bad "$msg"; echo "$o" | sed 's/^/   /' | head; fi; }
as()   { su "$U" -s /bin/bash -c "cd $H && $*"; }
appver() { as "cmllab version" 2>/dev/null | head -1 | awk '{print $NF}'; }
installed() { dpkg-query -W -f='${Status}' "$1" 2>/dev/null | grep -q "install ok installed"; }

for p in $P encorlab; do dpkg -s $p >/dev/null 2>&1 && apt-get purge -y $p >/dev/null; done
id "$U" >/dev/null 2>&1 || useradd -m -s /bin/bash "$U"
rm -rf "$H/.config"

OLD=$(ls $D/old-*.deb 2>/dev/null | head -1)
if [ -n "$OLD" ]; then
    OV=$(dpkg-deb -f "$OLD" Version)
    echo "== upgrade from the encorlab $OV package (ENCOR Lab Builder) to $P $VER"
    apt-get update -qq
    apt-get install -y "$OLD" > /tmp/apt-old.log 2>&1 && ok "apt install the encorlab $OV package" || { bad "install $OV"; tail /tmp/apt-old.log; }
    apt-get install -y -qq python3 procps >/tmp/apt-tools.log 2>&1
    as "python3 /src/packaging/upgrade3_test.py --phase old --old-exe /usr/bin/encorlab --base $H/.config --state /tmp/up3.json --new-version $VER --port 18850" > /tmp/up3-old.log 2>&1; rc=$?
    grep -E "^(PASS|FAIL|   how)" /tmp/up3-old.log | sed 's/^/   /'
    [ $rc = 0 ] && ok "the $OV updater links to encorlab_${VER}_amd64.deb ($(grep -c ^PASS /tmp/up3-old.log) checks)" || { bad "old phase rc=$rc"; tail -20 /tmp/up3-old.log; }
    chk "dpkg --verify encorlab clean" test -z "$(dpkg --verify encorlab)"
    # exactly what the old banner says: sudo apt install ./encorlab_<v>_amd64.deb
    (cd $D && apt-get install -y ./encorlab_${VER}_amd64.deb) > /tmp/apt-upg.log 2>&1 && ok "apt install ./encorlab_${VER}_amd64.deb over encorlab $OV" || { bad "upgrade $OV -> $VER"; tail /tmp/apt-upg.log; }
    grep -E "^(Removing|Unpacking|Setting up) " /tmp/apt-upg.log | sed 's/^/   /'
    installed $P && ! installed encorlab && ok "encorlab $OV replaced by $P $VER" || bad "packages: $(dpkg -l | grep -E 'encorlab|cml-lab' | awk '{print $1, $2, $3}' | tr '\n' ';')"
    chk "/opt/encorlab gone, /opt/$P there" test ! -e /opt/encorlab -a -x /opt/$P/$P
    chk "old command /usr/bin/encorlab -> $P (alias)" test "$(readlink /usr/bin/encorlab)" = $P
    chk "old menu entry gone, new one there" test ! -e /usr/share/applications/encorlab.desktop -a -f /usr/share/applications/$P.desktop
    v=$(appver); [ "$v" = "$VER" ] && ok "after the upgrade: $v" || bad "after the upgrade -> $v"
    as "python3 /src/packaging/upgrade3_test.py --phase new --new-exe /usr/bin/$P --base $H/.config --state /tmp/up3.json --port 18850" > /tmp/up3-new.log 2>&1; rc=$?
    grep -E "^(PASS|FAIL)" /tmp/up3-new.log | sed 's/^/   /'
    [ $rc = 0 ] && ok "data moved + 3.x patch round trip on the upgraded package ($(grep -c ^PASS /tmp/up3-new.log) checks)" || { bad "new phase rc=$rc"; tail -20 /tmp/up3-new.log; }
    chk "dpkg --verify $P clean after the patch round trip" test -z "$(dpkg --verify $P)"
    echo "== going back: apt install the encorlab $OV package again"
    apt-get install -y "$OLD" > /tmp/apt-back.log 2>&1 && ok "apt install ./$(basename "$OLD") over $P $VER" || { bad "back to $OV"; tail /tmp/apt-back.log; }
    installed encorlab && ! installed $P && ok "$P removed, encorlab $OV installed" || bad "packages after going back"
    v=$(as "encorlab version" 2>/dev/null | head -1); [ "$v" = "$OV" ] && ok "encorlab version -> $v" || bad "encorlab version -> $v"
    as "encorlab list" | grep -q troubleshoot-ospf-7node && ok "$OV still sees the labs" || bad "$OV lost the labs"
    (cd $D && apt-get install -y ./encorlab_${VER}_amd64.deb) > /tmp/apt-again.log 2>&1 && installed $P && ok "and forward to $P $VER again" || bad "forward again"
    v=$(appver); [ "$v" = "$VER" ] && ok "cmllab version -> $v" || bad "cmllab version -> $v"
    apt-get purge -y $P >/dev/null 2>&1; rm -rf "$H/.config"
fi

echo "== install $DEB"
apt-get update -qq
apt-get install -y "$DEB" > /tmp/apt-install.log 2>&1 && ok "apt install ./${P}_${VER}_amd64.deb (deps resolved)" || { bad "apt install"; tail -20 /tmp/apt-install.log; }
grep -E "^(Setting up|Unpacking) " /tmp/apt-install.log | sed 's/^/   /' | head -20
apt-get install -y -qq python3 desktop-file-utils procps >/tmp/apt-tools.log 2>&1 || { bad "test tools"; tail /tmp/apt-tools.log; }
chk "/usr/bin/$P is executable" test -x /usr/bin/$P
chk "/usr/bin/cmllab and /usr/bin/encorlab -> $P" test "$(readlink /usr/bin/cmllab)" = $P -a "$(readlink /usr/bin/encorlab)" = $P
chk "/opt/$P/install-type says deb" grep -qx deb /opt/$P/install-type
chk "dpkg: Provides encorlab" test "$(dpkg-query -W -f='${Provides}' $P)" = "encorlab (= $VER)"
chk "desktop-file-validate" desktop-file-validate /usr/share/applications/$P.desktop
chk "hicolor icons installed" test -f /usr/share/icons/hicolor/256x256/apps/$P.png -a -f /usr/share/icons/hicolor/48x48/apps/$P.png
chk "man pages installed" test -f /usr/share/man/man1/$P.1.gz -a -L /usr/share/man/man1/cmllab.1.gz
chk "dpkg --verify clean after install" test -z "$(dpkg --verify $P)"
v=$(appver); [ "$v" = "$VER" ] && ok "cmllab version as $U -> $v" || bad "cmllab version -> $v"
as "encorlab version" | grep -qx "$VER" && ok "old command name still works" || bad "encorlab alias"
as "cmllab update-status" | sed 's/^/   /'
as "cmllab update-status" | grep -q "Install type: deb" && ok "update-status reports install type deb" || bad "install type"

echo "== launch like the menu entry"
EXEC=$(sed -n 's/^Exec=//p' /usr/share/applications/$P.desktop)
printf '#!/bin/sh\necho "$1" >> /tmp/browser.log\n' > /tmp/fakebrowser; chmod 755 /tmp/fakebrowser; rm -f /tmp/browser.log
as "BROWSER=/tmp/fakebrowser nohup $EXEC > /tmp/launch1.log 2>&1 &"
up=0; for i in $(seq 60); do python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=1)" 2>/dev/null && { up=1; break; }; sleep 0.5; done
[ $up = 1 ] && ok "menu launch ($EXEC) starts the server on 127.0.0.1:8765" || { bad "server did not start"; cat /tmp/launch1.log; }
for i in $(seq 20); do [ -s /tmp/browser.log ] && break; sleep 0.25; done
grep -q "http://127.0.0.1:8765" /tmp/browser.log 2>/dev/null && ok "browser opened at $(head -1 /tmp/browser.log)" || bad "browser not opened"
n1=$(pgrep -c -f "^/opt/$P/$P") || true
out=$(as "BROWSER=/tmp/fakebrowser timeout 20 $EXEC" 2>&1); rc=$?
echo "   second launch: $(echo "$out" | tail -2 | tr '\n' ' ')"
[ $rc = 0 ] && echo "$out" | grep -qi "already running" && ok "second launch exits and reuses the running app" || bad "second launch rc=$rc"
[ "$(wc -l < /tmp/browser.log)" = 2 ] && ok "second launch only opened the browser again" || bad "browser log: $(cat /tmp/browser.log)"
n2=$(pgrep -c -f "^/opt/$P/$P") || true
[ "$n1" = "$n2" ] && ok "still one app instance ($n2 process(es))" || bad "processes $n1 -> $n2"
python3 -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8766/api/health',timeout=1)" 2>/dev/null && bad "a second server on 8766" || ok "no second server on the next port"
pkill -f "^/opt/$P/$P"; sleep 1

echo "== smoke test of the installed package as $U (patches + auto-update against a fake release)"
find /opt/$P -printf '%p %s %m\n' | sort > /tmp/opt.before
PACKS="--pack /src/library/ospf-multiarea-stub.cmllab --pack /src/library/troubleshoot-ospf-7node.cmllab"
as "python3 /src/packaging/smoke_test.py /usr/bin/$P --version $VER --data-dir $DATA --patch-test --auto-update-test $PACKS" > /tmp/smoke.log 2>&1; rc=$?
grep -E "^(PASS|FAIL)" /tmp/smoke.log | sed 's/^/   /'
[ $rc = 0 ] && ok "smoke test passed ($(grep -c ^PASS /tmp/smoke.log) checks)" || { bad "smoke test rc=$rc"; tail -30 /tmp/smoke.log; }
find /opt/$P -printf '%p %s %m\n' | sort > /tmp/opt.after
chk "/opt/$P untouched by patch installs" cmp /tmp/opt.before /tmp/opt.after
chk "dpkg --verify clean after patching" test -z "$(dpkg --verify $P)"
chk "nothing written to ~/.config/encorlab" test ! -e $H/.config/encorlab

echo "== upgrades: user patch $PV vs newer debs"
rm -rf "$DATA/app" "$DATA/updates"
as "cmllab update-install --file $D/user-patch-$PV.zip" | tail -1 | sed 's/^/   /'
v=$(appver); [ "$v" = "$PV" ] && ok "user patch $PV runs over deb $VER" || bad "after patch -> $v"
apt-get install -y "$D/${P}_${UP1}_amd64.deb" > /tmp/apt-up1.log 2>&1 && ok "apt install ./${P}_${UP1}_amd64.deb over $VER" || { bad "upgrade to $UP1"; tail /tmp/apt-up1.log; }
chk "dpkg --verify clean after upgrade" test -z "$(dpkg --verify $P)"
[ "$(dpkg-query -W -f='${Version}' $P)" = "$UP1" ] && ok "dpkg now has $UP1"
v=$(appver); [ "$v" = "$PV" ] && ok "newer user patch $PV keeps winning over bundled $UP1" || bad "after $UP1 deb -> $v"
apt-get install -y "$D/${P}_${UP2}_amd64.deb" > /tmp/apt-up2.log 2>&1 && ok "apt install ./${P}_${UP2}_amd64.deb over $UP1" || bad "upgrade to $UP2"
v=$(appver); [ "$v" = "$UP2" ] && ok "newer bundled $UP2 beats the $PV patch" || bad "after $UP2 deb -> $v"
chk "user data dir untouched by upgrades" test -d "$DATA/app/$PV" -a -d "$DATA/labs/ospf-multiarea-stub"

echo "== remove / purge"
apt-get remove -y $P > /tmp/apt-rm.log 2>&1 && ok "apt remove $P" || bad "apt remove"
chk "/opt/$P gone after remove" test ! -e /opt/$P
chk "commands gone after remove" test ! -e /usr/bin/$P -a ! -L /usr/bin/cmllab -a ! -L /usr/bin/encorlab
chk "menu entry gone after remove" test ! -e /usr/share/applications/$P.desktop
chk "~/.config/cml-lab-builder kept after remove" test -d "$DATA/labs/ospf-multiarea-stub"
apt-get purge -y $P > /tmp/apt-purge.log 2>&1 && ok "apt purge $P" || bad "apt purge"
grep -i "kept" /tmp/apt-purge.log | sed 's/^/   /'
chk "package fully gone from dpkg" test -z "$(dpkg -l $P 2>/dev/null | grep -E '^(ii|rc)')"
chk "~/.config/cml-lab-builder (data + app updates) kept after purge" test -d "$DATA/labs/ospf-multiarea-stub" -a -d "$DATA/app/$PV"

echo; [ $FAILS = 0 ] && echo "DEB CHROOT TEST PASSED" || { echo "DEB CHROOT TEST FAILED ($FAILS)"; exit 1; }
