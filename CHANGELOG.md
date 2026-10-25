# Changelog

All notable changes to CML Lab Builder (called ENCOR Lab Builder up to 2.1.0). Versions follow `MAJOR.MINOR.PATCH`.

## [3.3.4] - 2026-10-25
### Added
- **Mark a lab complete by hand when a check is buggy.** Walkthroughs get **Mark step done** (next to *Check this
  step* while the step's checks have not passed; **Undo mark done** removes it), so a failing check no longer blocks
  the step, and a lab-level **Mark lab complete** (challenge lab toolbar, walkthrough progress bar) with a confirm
  dialog and **Undo / mark incomplete**. Recorded as *completed manually*, distinct from a graded pass: challenge labs
  in `manual_complete.json` (never in the grading history), walkthroughs in their progress file (`manual_at` per
  step, `manual_completed` / `completed_manually`). A subtle dashed *marked manually* label shows on the step, the
  step bar, the lab list, the lab header, courses and the Progress page (new *Labs marked complete by hand* table;
  walkthroughs show *+N by hand*). Courses count it as complete (*x/y done* and *Continue* move on to the next lab);
  scores, mastery, *labs solved* and streaks are unchanged, and a later graded pass turns it into a normal one. New
  API `POST /api/labs/{id}/mark-complete?done=true|false` and `POST /api/labs/{id}/steps/{step}/mark-done?done=`
  (CSRF-protected like every POST). Native confirm dialogs, labelled buttons, no inline script (CSP unchanged); axe:
  0 violations in light and dark.

## [3.3.3] - 2026-10-25
### Changed
- **Walkthroughs scroll to the top of the new step.** **Next**, **Previous** and the step buttons in the progress bar
  used to leave the page where it was, usually at the bottom of the old step, in the middle of the new one. They now
  scroll the page (or the nearest scrolling container) so the top of the new step sits just below the sticky header
  (no offset on narrow screens, where the header is not sticky). The scroll is smooth, or instant when the OS or
  browser asks for reduced motion (`prefers-reduced-motion`); a nudge from the browser's scroll anchoring right after
  an instant jump is corrected on the next frame. Keyboard focus moves to the step heading (`tabindex="-1"`,
  `preventScroll`), so screen readers announce the step and Tab continues inside it, with no focus ring flicker on the
  heading (it is not a control). Checking or applying a step re-renders in place without scrolling. New
  `static/walkscroll.js` (no inline script; the CSP is unchanged), tested with node and in Chrome (axe: 0 violations).

## Library update - 2026-10-25 (no app release)
Library-only change: the apps pick up the new lab versions from the online library (*Library & courses* shows
*update* on installed copies). No new executables.

### Changed
- **NX-OS study path labs 21-23 (now version 3): standard Clos, no SS1-SS2 link.** The super-spine interconnect
  (SS1/SS2 Ethernet1/3) is removed from the CML topology, the day-0 configs and the lab 22/23 baselines
  (regenerated with `packaging/nxos_study_baseline.py`): Ethernet1/3 on SS1/SS2 is now *unused* and shut. Diagrams,
  port/link tables and the area 0 description follow Cisco's standard Clos (links only between adjacent stages).
  Lab 21 step 0 explains why super spines never interconnect (every path up-down, uniform hop count, predictable
  ECMP, no extra ports). Steps, checks, expected outputs, hints and the debug-filter example no longer use
  SS1-SS2: SS1/SS2 have 2 OSPF neighbors, router LSAs have 3 links, SS1 reaches SS2 (10.0.0.2) by ECMP through
  both spines (new check in labs 21 and 22), P1-SPINE reaches pod 2 at cost 121, the MTU fault moves to SS2
  Ethernet1/1, and the lab 22 convergence drill now detours P1-SPINE -> SS2 -> P2-SPINE -> SS1. Labs 22/23 explain
  that the route reflectors do not peer with each other; an optional RR-to-RR session would run loopback to
  loopback through the spines (ECMP, survives either spine), never over a cable between the super spines.
- **Lab 21: NX-OS OSPF database commands need `detail`.** Real 9000v output showed that
  `show ip ospf database router 10.0.0.11` prints only the summary table (Link ID / ADV Router / Age / Seq# /
  Checksum / Link Count), unlike IOS. The step 3 check for P1-SPINE's links and the NSSA/external verifies that
  expect LSA fields (Link Data, metric type, forwarding address) now use `... detail`; the summary view gets its
  own check (P1-SPINE Link Count 3 = 2 p2p links + the loopback stub) matched only on stable tokens and tested
  against the real output, and step 3 explains the NX-OS/IOS difference (ABRs originate one router LSA per area).

## [3.3.2] - 2026-10-24
### Fixed
- **"Your resource pool allows 1 nodes" on CML Personal.** 3.3.1 read `user_quota` / `user_started` from CML's
  licensing diagnostics as a per-user node limit. They are not: on a CML 2.9.1 Personal server `user_quota` is 1
  while 0 of 20 node licenses are in use, so every lab was *won't fit* even though memory and the 20 node licenses
  were fine. Those numbers are no longer used. A per-user limit is now taken only from the login's assigned CML
  resource pool when its limit has a number of node licenses (`GET /users/{id}` -> `resource_pool`, then
  `GET /resource_pool_usage/{pool}`); no pool, `licenses: null` (unlimited) or an unreadable pool never blocks. The
  node line shows the pool (*your resource pool: n of m*) when one applies.

### Added
- **Copy diagnostics** button in the Build box and `cmllab resource-diagnostics [-o file]`: the raw licensing,
  licensing-diagnostics, system-stats and resource-pool JSON the check used plus the app's view of it, with
  passwords, tokens, serials / UDI, accounts, ids, host names, user names, URLs and IP addresses removed, for bug
  reports. Read-only.

## [3.3.1] - 2026-10-24
### Fixed
- **Resource check read the wrong license.** 3.3.0 added up `max` / `in_use` of every CML license feature, so on a
  CML Enterprise server it showed the base license (*1 of 1*) as the node count and every lab as *won't fit*. The
  capacity is now the nodes included with the license (from its description, e.g. *"20 nodes capacity included"*, or
  the product: Personal 20, Personal Plus 40, Enterprise 20, Free 5) plus the *Expansion Nodes* in use (not its 300
  maximum); nodes in use come from CML's licensing diagnostics, else from the running labs. When the license can't be
  read or isn't clear, the node check says **can't tell** instead of *won't fit*.
- **"Won't fit" with enough RAM.** The memory bar and summary took their colour and wording from the overall verdict,
  so a node-license failure looked like a memory problem. Memory and node licenses are now separate lines (fits /
  tight / won't fit / can't tell) and the summary names the limit that failed. Free memory now counts reclaimable
  page cache (`total - used` when that is more than *free*), and memory reported in KiB is recognised.
- Unmanaged switches and external connectors no longer count toward licensed nodes (lab and running labs).
- The CML resource-pool node quota is checked when CML reports it.
- **NX-OS consoles (lab 21-23 switches boot but the console did not work):** a quiet NX-OS boot phase is no longer
  taken for an unrecognised prompt (an unchanged last line is waited out for about 5 minutes on NX-OS, 1 minute on
  IOS); `loader>` is recognised with a clear error (wipe and start the node, or Reset the lab); *Test console* now
  tries the same logins as a check, including *Settings > NX-OS login*, and waits up to 10 minutes on NX-OS.

### Added
- **Collapsible lab list** on the Labs page: *Hide lab list* / *Show lab list* gives the directions the full width.
  Keyboard and screen-reader friendly (`aria-expanded`, `aria-controls`, visible focus), light and dark, remembered
  in the browser; folds away by itself in narrow windows (900 px or less) once a lab is open unless you chose
  otherwise; **/** reopens it.

## Library update - 2026-10-24 (no app release)
Library-only change: the apps pick up the new lab versions from the online library (*Library & courses* shows
*update* on installed copies). No new executables.

### Changed
- **NX-OS study path labs 21-23 (now version 2): IP-unnumbered OSPF underlay.** Every fabric link (the four
  super-spine-to-spine links, SS1-SS2 and both spine-to-leaf links) is now `no switchport` + `medium p2p` +
  `mtu 9216` + `ip unnumbered loopback0` with `ip ospf network point-to-point`, instead of six /30s and a /24:
  280 link addresses saved, the loopbacks are the only addresses left. Loopback0 is created before the links
  borrow it and stays unique per switch (router ID = loopback0, checked by a test). Lab 21 rewrites the address
  table, the step explanations (why unnumbered, `medium p2p` before `ip unnumbered`, next hops = neighbor
  loopbacks, router LSA Link Data = ifIndex, no /30 stub networks, no DR and no network LSA on an all-p2p fabric),
  the checks (link pings replaced by interface checks and a loopback ping after OSPF, `FULL/ -` on SS1-SS2,
  ECMP via 10.0.0.1/10.0.0.2, `Num nets: 2` in the pod summaries) and adds a "borrowed loopback shut" fault to
  break-and-fix. Labs 22 and 23 update their baselines (regenerated with `packaging/nxos_study_baseline.py`)
  and expected outputs; lab 22's eBGP design discussion now shows how to peer over unnumbered links. The IOL
  hosts are not on fabric links and keep their day-0 (iol-xe rule unchanged).
- **Lab 23: new required step 13, `retain route-target all` on the spines and super spines.** Configured under
  `router bgp 65000` / `address-family l2vpn evpn` on SS1, SS2, P1-SPINE and P2-SPINE; the spines get
  `nv overlay evpn` and the L2VPN EVPN family towards the RRs, so they keep every EVPN route although they import
  no RT (checked: config on all four, spine EVPN sessions with prefixes, type-3 routes kept on P1-SPINE). The step
  explains what the command does and corrects a common claim: it does **not** remove BGP path hunting - in an
  eBGP Clos that is solved by one ASN per spine tier. Later steps renumbered (14 ARP suppression, 15 break and
  fix, 16 wrap-up).

## [3.3.0] - 2026-10-24
### Security
- **Security audit and hardening** (details in the new [SECURITY.md](SECURITY.md)):
  - **Signed updates:** releases carry Ed25519 signatures of `SHA256SUMS.txt` and of the patch (`*.sig`); the
    public release key is built into the app. From this version on, unsigned or wrongly signed updates are refused
    (online and *Install update from file*). Up to 3.2.0 apps keep checking `SHA256SUMS.txt` as before.
  - **Web UI guards:** Host allowlist against DNS rebinding (421), CSRF protection (`Origin` / `Sec-Fetch-Site`
    checks plus a required `X-CMLLab-Request` header), CORS preflights refused, path traversal guard.
  - **Per-launch access token** in the desktop app (HttpOnly SameSite=Strict cookie after the first open), so
    other local users or programs cannot drive the UI. `CMLLAB_ACCESS_TOKEN=0` turns it off. `cmllab web --token`.
  - `cmllab web --host` with a non-loopback address prints a loud warning and always requires a token.
  - **Strict Content-Security-Policy** (no inline script or event handlers any more), `nosniff`,
    `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `Referrer-Policy: no-referrer`, COOP/CORP. Links built from
    lab or library data only allow http(s).
  - **Secrets:** device passwords are now remembered too (OS keyring) when *Remember passwords* is ticked; without a
    keyring, secrets go to `secrets.json` (0600) instead of being dropped, and move into the keyring once there is
    one. A password found in `settings.json` is moved out at start; `settings.json` is written 0600.
  - Secrets are redacted from job output, errors, tracebacks and startup errors; the access log is off.
  - **TLS:** new *TLS verification > On, with my own CA certificate* (PEM path, checked in Settings); *Off* is
    labelled insecure and shows a warning in Settings and in the log.
  - Zip member checks also reject `\` and NUL; ids used as file names are checked.
  - CI: security lint (ruff `S` rules) and `pip-audit`; the deb test checks file ownership and permissions.
- Known limitation: a report saved as HTML by the CLI and opened from disk keeps working, but its *Print* button
  needs the app (`Ctrl+P` works everywhere).

### Added
- **Resource check before Build:** the Build box reads free memory, licensed nodes and running labs from CML and says
  *Fits*, *Tight*, *Won't fit* or *Can't tell*, with a memory bar and the running labs (nodes, RAM). Stop a lab, or
  stop & wipe one this app built, from there (with confirmation), then build, *Build anyway* or cancel. A running
  copy of the same lab counts as free. Library cards show *fits now?* tags (cached 30 s). New settings *Check free
  CML memory before Build* and *Keep this much CML memory free* (`CMLLAB_RESOURCE_CHECK`,
  `CMLLAB_RESOURCE_HEADROOM_GB`, default 4 GB). Errors (no admin rights for system stats, CML down) show *Can't
  tell* and never block a build. New API: `GET /api/resources`, `GET /api/labs/{id}/precheck`,
  `POST /api/cml/labs/{id}/stop`.
- **New library lab `21-nxos-ospf-multiarea`: NX-OS study path 1/3: OSPF multi-area on a super-spine Clos, with deep
  debug inspection** (walkthrough, 12 steps). Six Nexus 9000v in a 5-stage Clos (SS1/SS2, one spine and one leaf per
  pod) plus four IOL hosts, 10 nodes, about 76 GB of CML RAM. Area 0 on the super-spine layer, one area per pod with
  the spines as ABRs, a DR/BDR segment, `area range` summarization, an NSSA with a translated external and a stub
  area. Each step explains what NX-OS does under the hood and lists the show, event-history and debug commands
  (`debug logfile`, `debug-filter`, `undebug all`) to inspect it. Library only: `library/21-nxos-ospf-multiarea.cmllab`
  (and `labs/21-nxos-ospf-multiarea.encorlab`). Expected outputs are synthesized from Cisco documentation.
- **New library lab `22-nxos-bgp-over-ospf`: NX-OS study path 2/3: iBGP over OSPF with super-spine route reflectors,
  with deep debug inspection** (walkthrough, 12 steps, same 10-node / 76 GB topology). Boots from its own baseline:
  lab 21's day-0 plus lab 21's required steps. SS1/SS2 as route reflectors with peer templates, loopback peering,
  the BGP FSM with `event-history` and filtered debugs, next-hop tracking, best-path selection between reflected
  copies, the BGP-free-core problem, optional community/local-preference policy, eBGP and BFD design discussions
  (BFD is not supported on Nexus 9000v). `packaging/nxos_study_baseline.py` regenerates the study-path baselines; a
  test fails if one drifts.
- **New library lab `23-nxos-evpn-vxlan`: NX-OS study path 3/3: BGP EVPN VXLAN over iBGP and OSPF (L2VNI, L3VNI,
  anycast gateway), with deep debug inspection** (walkthrough, 16 steps, same 10-node / 76 GB topology). Boots
  from its own baseline: lab 22's day-0 plus lab 22's required steps. L2VPN EVPN on the existing RR sessions,
  VLAN-to-VNI mapping, NVE with BGP ingress replication (multicast underlay explained), cross-pod bridging,
  L3VNI with anycast gateway and symmetric IRB, type-5 prefixes, optional ARP suppression and break/fix.
- **New course `nxos-study-path`: NX-OS study path: OSPF → BGP → BGP EVPN VXLAN** (labs 21, 22, 23 in order;
  `library/nxos-study-path.cmlcourse`, `labs/nxos-study-path.encorcourse`).

### Changed
- **Design refresh** following common design-system practice: design tokens (8 px spacing grid, a type scale,
  semantic colors) for both themes; consistent buttons (36 px), inputs, tags, chips, cards, tables and callouts;
  inline SVG icons instead of emoji (CSP-safe, no CDN); header with a brand mark and a sun/moon theme toggle;
  loading spinners, empty and error states styled the same everywhere.
- **Accessibility (WCAG 2.2 AA):** contrast fixed in both themes (muted text, the walkthrough tag, primary buttons in
  dark mode, library topic names), a visible focus ring on every control, a *Skip to content* link, labelled progress
  bars, `aria-expanded` on the *More* menu, `prefers-reduced-motion` honored (also for scrolling), forced-colors mode
  support, a layout that reflows to phone width without horizontal scrolling. axe-core reports 0 violations on Labs, a
  walkthrough step, Library, Settings and the resource check, light and dark (3.2.0: 94).

## [3.2.0] - 2026-10-23
**Library sorted by topic.** A patch for 3.0.0 and 3.1.0 (same runtime 2): they offer it by themselves and install it
with *Install update*. ENCOR Lab Builder 1.7 - 2.1 still get the *full download* banner.
### Added
- **Topic tags** for every library lab and course, from one controlled list (`cmllab/topics.py`): OSPF, EIGRP, BGP,
  Redistribution & PBR, VLAN / STP / EtherChannel, HSRP / FHRP, IP services (NAT, NTP), Multicast, VRF, GRE / IPsec,
  MPLS, EVPN / VXLAN, Data center, Security, QoS, Monitoring & assurance, Automation, Troubleshooting, Other, plus
  Walkthrough / Challenge and the track (ENCOR). The library labs get theirs in `labsrc/library.yaml` (`topics:`;
  `build_library.py` refuses unknown topics and labs without any), and both `library/index.json` and
  `labs/index.json` carry them. Courses get the most common topics of their labs. Labs from an index without topics
  (other libraries) get derived ones: ENCOR blueprint items, keywords in the id, title, domain and description, and
  node types (`nxosv9000` = Data center). `/api/library` also returns the topic list (`topics`).
- **New library layout:** a row of topic chips with counts (multi-select: any of the topics picked in one area, all
  of the areas), labs grouped under collapsible topic headings (*Expand all / Collapse all*) or one flat list
  (*Grouped by topic / List*), and compact cards instead of the table: title, Walkthrough / Challenge, difficulty,
  node count, RAM with the red *RAM heavy* tag, starter / installed / update status, and topic chips that filter
  when clicked. Works in light and dark mode and on narrow windows (one column).
- **Search knows the topics:** the 3.1.0 fuzzy search also matches topic names (`monitoring`, `data center`, `gre
  ipsec`), and search, topics and the other filters combine. Still client-side and about 1 ms per keystroke for
  300 labs.
- The library remembers the view, the selected topics and the collapsed groups (browser `localStorage`).
- Keyboard and screen readers: chips are toggle buttons (`aria-pressed`, arrow keys move between them), the topic
  headings are buttons with `aria-expanded`, and the chip row and the lists are labelled.
### Compatibility
- The lab packs are unchanged (the topics are only in the index, the lab format rejects unknown fields), so no lab
  versions changed and no *Update available* shows up. Apps 2.0 - 3.1 ignore the new index field (checked with the
  2.0.0, 2.1.0, 3.0.0 and 3.1.0 builds: they load the new index and install from it), and 1.7 - 1.9 parse it too.

## [3.1.0] - 2026-10-23
**Fuzzy search in the library**, plus the library updates below. A patch for 3.0.0 (same runtime 2): 3.0.0 offers it
by itself and installs it with *Install update*. ENCOR Lab Builder 1.7 - 2.1 still get the *full download* banner.
### Added
- **Search bar in *Library & courses*.** Filters the online library as you type and ranks the results, best first,
  with the matched letters highlighted. It searches titles, lab ids, descriptions, topics (blueprint items and
  domains), the courses a lab is in, platforms and node types (`iol-xe`, `nxosv9000`, or *nexus*, *nx-os*, *ios-xe*).
  The matching is fuzzy: it tolerates typos (`mutlicast`, `redistrbution`; 1 edit for 4-7 letters, 2 for longer
  words) and accepts abbreviations and partial words (`vrf lit`, `ospf stb`, `mcast`, `evpn mpls`). Each word must
  match. It works together with new filters for labs/courses, installed / not installed / update available, one
  course, and *Hide RAM heavy*. `/` or `Ctrl+K` jumps to the box, `Esc` clears it, and a message with *Clear search
  and filters* appears when nothing matches. It all runs in the page over the index that is already loaded
  (`static/fuzzy.js`, no dependencies): no server calls while typing, the text is normalized once per load, and only
  the word being typed is re-scored. About 1 ms per keystroke for 300 labs. The lab list's *Search labs* box now uses
  the same fuzzy, ranked and highlighted matching.
- **Library index search fields:** lab entries in `library/index.json` (and `labs/index.json`) now carry `domain`,
  `track`, `platforms` and `node_types`, and `/api/labs` reports `track` and `node_types`. Older apps ignore the new
  fields, and older indexes still load; search then simply has less to match.
- **New library lab `19-evpn-mpls`: Walkthrough: BGP EVPN over MPLS (IOS-XE, IOL).** 8 `iol-xe` nodes (about 8 GB
  RAM): OSPF + LDP core, iBGP `l2vpn evpn` through a route reflector, VLAN-based EVIs 10/20 with bridge domains and
  service instances stretching two VLANs across three sites, route type 2/3 and MAC verification, same-VLAN pings,
  and an optional EVPN-VPWS step. Published as `library/19-evpn-mpls.cmllab` (and `labs/19-evpn-mpls.encorlab` for
  2.x). Expected outputs come from Cisco documentation and are not yet verified on CML.
- **New library lab `20-evpn-vxlan-superspine`: Walkthrough: BGP EVPN VXLAN across two data centers with super spines
  (5-stage Clos).** 12 nodes (4 `nxosv9000` leaves, 4 `iol-xe` spines/super spines, 4 IOL hosts; about 56 GB RAM, RAM
  heavy): OSPF underlay through leaf - spine - super spine - spine - leaf, iBGP `l2vpn evpn` with the super spines as
  route reflectors, VLANs 10/20 as L2VNIs 10010/10020 on NVE VTEPs with BGP ingress replication, same-VLAN pings from
  DC1 to DC2, and an optional L3VNI VRF with a distributed anycast gateway. Published as
  `library/20-evpn-vxlan-superspine.cmllab` (and `labs/20-evpn-vxlan-superspine.encorlab` for 2.x). Expected outputs
  come from Cisco documentation and are not yet verified on CML.
### Fixed
- **Library labs `19-evpn-mpls` and `20-evpn-vxlan-superspine` (now version 2): the routers booted with no day-0
  config on CML** (no hostname, unconfigured CEs/hosts, IOL setup dialog). Cisco's `iol-xe` node definition requires
  every Ethernet port to have some IP configuration in the day-0 config, or IOL ignores the whole config and starts the
  initial configuration dialog; the hostname-only core routers and the CEs/hosts (only their cabled ports) did not.
  Every IOL node now lists all four ports (description, `no ip address`, cabled links `no shutdown`, unused ports
  `shutdown`), so the hostname, `no ip domain lookup` and the CE/host configs apply, and the step 1 CDP check sees
  its neighbors. The Nexus leaves in lab 20 also get port descriptions and their links enabled. Update both labs in
  the library, then destroy and rebuild them in CML.
- **Library lab `08-vrf-lite` (now version 2): PE booted with no day-0 config on IOL** (no hostname, setup dialog):
  its two ports had descriptions but no IP configuration, the same IOL trigger as above. Every IOL node (PE, CEA, CEB)
  now lists all four ports (`no ip address` on the PE links, descriptions on the CE links, unused ports shut); the
  customer configs are unchanged. An audit of every library lab found no other `iol-xe` node without IP configuration
  on an Ethernet port (IOL L2 switches have no such requirement), and a test now checks the whole library. Update
  the lab in the library, then destroy and rebuild it in CML.
- **Library lab `19-evpn-mpls`:** *Apply this step* on the BGP EVPN step no longer sends a stray
  `exit-address-family` in router configuration mode (where IOS rejects it) on the RR and PE1-PE3. The line was removed
  from the step config. Installed copies show *Update available* in the library.
- **CI: the Debian package check (`deb-test`) failed on 3.0.0 although the package was fine.** The workflow ended with
  `test -d ~/.config/cml-lab-builder/app`, but the smoke test removes its test patches (`<data>/app`) when it
  finishes, so that line could never pass; it failed silently because the plain `test` lines printed nothing. The
  job now runs `packaging/deb_docker_test.sh`: the same checks as the local `deb_chroot_test.sh` (install with
  dependencies, menu launch, single instance, smoke test with patch + auto-update as a normal user, `/opt` and
  `dpkg --verify` unchanged, upgrades over a user patch, remove + purge keep the data), in a `debian:12` container
  pinned by digest. Each check prints PASS/FAIL, and a failure lists the failed checks plus the log tails. The test
  waits for the server port and for the app to stop, polls state files instead of sleeping, and retries apt.

## [3.0.0] - 2026-10-21
**The full rename: the program, downloads, package, data and CML labs are all CML Lab Builder now.** This is a full
download (new runtime 2), not a patch. ENCOR Lab Builder 1.7 - 2.1 find it by themselves and show *a full download
is needed* with a direct link; your data moves on the first start. See *Upgrading from ENCOR Lab Builder* in the README.
### Changed
- **Program:** `CMLLabBuilder.exe` on Windows, `cml-lab-builder` on Linux (was `ENCORLab(.exe)`), with the new name in
  the Windows file properties and a renamed icon.
- **Downloads:** `CMLLabBuilder-<v>-windows-x64.zip`, `CMLLabBuilder-<v>-linux-x64.tar.gz`,
  `cml-lab-builder_<v>_amd64.deb`; app patches are `cml-lab-builder-patch-<v>.zip`. 3.x only looks for these names.
- **Debian package `cml-lab-builder`:** installs to `/opt/cml-lab-builder` with `/usr/bin/cml-lab-builder` and
  `/usr/bin/cmllab`, menu entry `cml-lab-builder.desktop`, icons, `man cml-lab-builder`, docs in
  `/usr/share/doc/cml-lab-builder`. It declares `Replaces/Breaks/Conflicts: encorlab (<< 3.0.0~)` and
  `Provides: encorlab`, so `sudo apt install ./cml-lab-builder_3.0.0_amd64.deb` swaps out the old `encorlab` package in
  one step. `/usr/bin/encorlab` stays as an alias until 4.0.
- **Python package `cmllab`** (was `encorlab`; distribution `cml-lab-builder`): `python -m cmllab`, commands `cmllab`
  and `cml-lab-builder` (`encorlab` is a temporary alias). Boot loader `cmlboot.py`, entry point `cmllab_launcher.py`,
  spec `packaging/cmllab.spec`, schema `docs/cml-lab.schema.json`.
- **Runtime 2:** the boot loader keeps installed updates in the data folder, `cml-lab-builder/app` (was `encorlab/app`),
  and loads the `cmllab` package. Patches for runtime 1 (ENCOR Lab Builder) are not used.
- **Labs in CML are titled `CML-<lab>`** (test copies `CML-TEST-<lab>`, tag `cml-lab-builder`). Labs built by ENCOR Lab
  Builder (`ENCOR-<lab>`) are still found: Check, Reset, consoles, snapshots and Destroy work on them (consoles use their
  real title), and *Rebuild* replaces them with a `CML-` copy. Nothing else is ever deleted.
- **Environment variables are `CMLLAB_*`.** `ENCOR_*` still work (copied to the new name at start; `CMLLAB_*` wins).
- **Everything else:** user agent `cml-lab-builder/<v>`, log and thread names, CI workflow and artifact names, build
  scripts, desktop entry of the tar.gz (`cml-lab-builder.desktop`), README-FIRST, UI texts (import `.cmllab` /
  `.cmlcourse`; the file picker also accepts the old extensions, which it did not list in 2.1.0).
- **The two example packs** (`ospf-multiarea-stub`, `troubleshoot-ospf-7node`) have the new name in their README and
  author (version 2, so installed copies are offered the update).
### Upgrading from ENCOR Lab Builder
- **Old apps see 3.0.0:** the release carries a manifest-only `encorlab-patch-3.0.0.zip` (`min_runtime` 2, no files) and
  byte-identical copies of the downloads under the old names (`ENCORLab-3.0.0-windows-x64.zip`,
  `ENCORLab-3.0.0-linux-x64.tar.gz`, `encorlab_3.0.0_amd64.deb`). 1.7 - 2.1 verify the stub against SHA256SUMS, see
  "needs runtime 2" and show the full-download banner linking the copy for their install type (the .deb banner's
  `sudo apt install ./encorlab_3.0.0_amd64.deb` installs the new package). Nothing is installed by the old app.
  `packaging/build_compat.py` builds these; CI's release job adds them to every 3.x release.
- **Data on the first start:** from 2.1 (data already in `cml-lab-builder`) nothing is copied again and the old
  folder's `MOVED.txt` now says the whole folder may be deleted; from 1.7 - 2.0 the automatic move of 2.1.0 runs (copy,
  SHA-256 check, one rename, keyring entry, `MOVED.txt`); from 1.x the formerly built-in labs are restored from the
  library with scores linked. A stale "download 3.0" banner state from the old app does not come back.
### Tests
- `packaging/upgrade3_test.py` runs the real 1.9.0, 2.0.0 and 2.1.0 builds (Linux, and Windows under Wine) against a
  fake 3.0.0 release, then 3.0.0 on their data, then a 3.0.1 patch round trip; the Debian chroot test upgrades from the
  real `encorlab_2.1.0_amd64.deb` with exactly the command the old banner shows. `tests/test_rename3.py` covers the boot
  loader folder, env aliases, legacy lab titles, the transition files and the absence of old names in the program.
  `migration_test.py` and `rename_test.py` (1.x -> 2.x and 2.0 -> 2.1 by patch) were removed: those patches cannot be
  built from the 3.0 tree.
### Kept on purpose
- ENCOR as a track, course and exam-domain name, and in lab content. The `labs/` library folder with `.encorlab` /
  `.encorcourse` names for 2.0 and older, import of those extensions, the `encorlab-cml` keyring entry (read), the
  `encorlab` data folder (read once, never deleted), `ENCOR_*` env vars and `ENCOR-` lab titles (recognised), and the
  `encorlab` command alias (until 4.0).

## [2.1.0] - 2026-10-20
**ENCOR Lab Builder is now CML Lab Builder**, because not every lab is for ENCOR. Delivered as a normal in-app patch
to 1.7-2.0 installs (the runtime is unchanged); your data moves to the new folder name by itself on the first start.
### Changed
- **New name everywhere you see it:** window and console title, web UI, help, reports, CLI help, menu entry (from the
  2.1.0 .deb), docs and release notes. ENCOR stays where it is ENCOR content: lab tags, courses, the ENCOR exam domains.
- **GitHub repo renamed** to `Specops13/cml-lab-builder` (old `encore-lab-app` links, the releases API, downloads and raw
  library URLs redirect). The updater and library default to the new repo.
- **Data folder renamed** to `%APPDATA%\cml-lab-builder` / `~/.config/cml-lab-builder`. On the first start everything in
  the old `encorlab` folder is copied, checked by SHA-256 and put in place in one rename, the keyring password is
  copied to the new name, `MOVED.txt` is left in the old folder (nothing is deleted) and a one-time note says *Your data
  moved to ...*. Files the old version writes later (after a rollback) are copied over on the next start without
  overwriting anything. If the copy fails, the old folder keeps being used. Installed app updates (`app/`) stay in the
  old folder because the installed boot loader looks there; patch, restart and rollback work as before.
- **File types:** labs export as `.cmllab` and courses as `.cmlcourse`. `.encorlab` / `.encorcourse` still import.
  The library is published in `library/` with the new names; `labs/` keeps the same labs under the old names for 2.0
  and older.
- **Commands:** `cmllab` and `cml-lab-builder` (pip / source; `/usr/bin/cmllab` in the 2.1.0 .deb); `encorlab` stays.
- **Environment:** every `ENCOR_…` variable can also be written `CMLLAB_…` (wins if both are set).
- **Progress per track:** labs may set `track:` (default `ENCOR`). The Progress page and report show a Tracks table;
  the ENCOR exam-domain view only counts ENCOR labs and only appears when you have some. Non-ENCOR labs no longer get
  the "unknown blueprint item" warning. The Lab builder has a Track field.
### Fixed
- **NX-OS (nxosv9000) console sessions, e.g. the EVPN-VXLAN labs:** after logging in, commands timed out because NX-OS
  sends a bare `\r` before its prompt (`\r\r\n` line ends) and the prompt pattern required a line start. Line ends,
  ANSI/OSC escape codes and backspaces are now normalised before matching. Also fixed: the console server's own
  `consoles>` prompt was taken for a device prompt; `terminal width 0` (invalid on NX-OS) is now `terminal width 511`;
  `--More--` paging is answered; slow output is waited for while data keeps arriving; the POAP / secure password /
  admin password / basic setup dialog is answered; after the console exec-timeout the app logs in again, trying the new
  *NX-OS login* setting, the device login, then `admin` with the device password, `admin`/`cisco`, `admin`/`admin`.
  A node that is not running gives that message instead of a timeout, and a console that keeps showing a prompt the
  app does not recognise fails within a minute instead of waiting for the boot timeout.
- **Console errors show the real reason** with the last 20 console lines (Results output, Activity log, Test console).
- **SSH host key:** no more `UserWarning: Unknown ssh-rsa host key`. The key is stored on first use in
  `<data>/known_hosts`; *Settings* shows its fingerprint with **Forget host key**; a changed key stops with a clear error.
### Added
- **Test console** in the lab view: per node, reports each stage (SSH to the console server, open the node, prompt
  detected, login needed, command ran) with the raw last console lines (`POST /api/labs/<id>/console-test?node=`).
- Settings: *NX-OS login* (username / password; the password is kept like the CML password), device login fields.
- `GET /api/data-folder`, `POST /api/data-folder/ack`, `GET /api/console/hostkey`, `POST /api/console/hostkey/forget`.
### Kept (renamed in a later full release)
- The program file `ENCORLab` / `ENCORLab.exe`, the download asset names, the .deb package `encorlab` and `/opt/encorlab`,
  the patch file name `encorlab-patch-<v>.zip`, the Python package `encorlab`, and the `ENCOR-<lab>` lab titles in CML
  (renaming those would orphan labs you have already built). Old updaters (1.7-2.0) depend on these names.

## [2.0.0] - 2026-10-20
The app now ships without labs; every lab comes from the online lab library. This is a behaviour change for new
installs (a first start has no labs), hence 2.0.0. Existing users keep everything, and the runtime is unchanged, so
1.7.x-1.9.x installs update in place with the small patch.
### Changed
- **No labs in the downloads.** The 19 former built-in labs (including the EVPN walkthrough) moved from
  `encorlab/labs/` to `labsrc/` and are published as packs in the lab library (`labs/`, with sha256, size, version, RAM
  estimate and a recommended starter set in `labs/index.json`). The Windows zip, Linux tar.gz, .deb and patch contain no
  labs, and the example packs folder (`example-packs/`) is gone from the downloads too.
  - Honest numbers (1.9.0 -> 2.0.0, bytes): Windows zip 26,577,567 -> 26,489,377 (-86 KB, -0.3%), Linux tar.gz
    33,453,768 -> 33,398,858 (-54 KB, -0.2%), .deb 27,876,152 -> 27,824,844 (-50 KB, -0.2%), patch 276,109 -> 184,693
    (-89 KB, -33%). The labs were only ~300 KB uncompressed; the downloads are dominated by the Python runtime and
    libraries. The big win is a clean start: a new user picks what they want instead of facing 19 labs at once.
- Courses list library labs instead of relying on built-in ones. *Install all* (library) installs a course plus every lab
  it lists that you don't have; importing a course file does the same when online.
- *Delete lab* keeps the lab's results history by default (it links up again when you re-install the lab); the UI asks
  whether to delete the history too (`DELETE /api/user-labs/<id>?clear_history=true`).
- The library accepts plain http only for a library on localhost (for local mirrors and testing); https elsewhere.
### Added
- **A clean welcome screen on the first start** (no labs yet): three choices side by side. **Start with the basics**
  (recommended) lists the six starter labs with their RAM estimate and total download size, and installs them in one
  click with **Install recommended starter set**. **Follow a course** opens *Browse library & courses*, and **Got a lab
  file?** imports a .encorlab file. Empty filters are hidden, and a hint points to Settings while no CML server is set.
  When the library can't be reached, a plain "can't be reached right now" note offers *Try again* (technical details below
  it); everything else keeps working offline.
- **Library view:** sizes, RAM estimates (red *RAM heavy* tag), *starter* and *installed vN* tags, *Install starter set*,
  per-course *Install all (N labs)*, and **Update available** / *Update to vN* / *Update all* when the library has a newer
  lab version (`version:` in lab.yaml, compared numerically). The lab list and lab page show *update available* too.
- **Settings > Library URL** (`library_url`, `ENCOR_LIBRARY_URL`); empty means this repository.
- **Keeping the labs 1.x bundled** (`encorlab/migrate.py`): on the first start of 2.x an existing installation gets
  every formerly bundled lab back under the same id.
  - Updated by patch: copied from the old program files still on disk (the runtime's bundled 1.x app code or an
    installed 1.x patch, newest copy wins). Works offline.
  - Updated by full download: installed from the library in the background. Until then a banner offers *Restore now* /
    *Dismiss* (CLI: `encorlab library restore`).
  - History, reports, walkthrough progress, snapshots, faults and exams are never touched, and an existing lab folder is
    never overwritten. Fresh installs are detected and skip all of this.
- CLI: `library install --starter | --all | --updates`, `library restore`; `library list` shows size, RAM, installed /
  update and the starter set; `list` on an empty install explains how to get labs.
- API: `POST /api/library/install-set` (starter / ids / updates), `GET /api/migration`, `POST /api/migration/restore`,
  `POST /api/migration/dismiss`; `/api/labs` adds `version`, `library`, `update_available` and `migration`.
- `packaging/build_library.py` validates every lab strictly, writes versions and the starter set (`labsrc/library.yaml`)
  and refuses a changed lab pack whose `version:` was not raised.
- Tests: first run, starter set, course *Install all*, offline, updates, version ordering, delete-keeps-history, every
  library pack installs and validates, and migration (patch, bundled runtime copy, full download, offline, broken
  source lab, never overwriting, background restore, dismiss). The smoke test now starts with no labs and installs the
  starter set and a course from a library served on 127.0.0.1. A new `packaging/migration_test.py` runs both update
  paths against the real 1.9.0 and 2.0.0 builds (passed on Linux and on Windows under Wine).
- Developers: `ENCOR_BUILTIN_LABS_DIR=labsrc` uses the lab sources in place (the test suite does this).
### Docs
- README (first start, library, updating from 1.x), lab authoring guide (`version:`, publishing in the library, courses
  with library labs), AI prompt (`version:` guidance) and the JSON Schema (`version` description).

## [1.9.0] - 2026-10-19
### Added
- **Walkthrough labs** (`type: walkthrough`): a guided build in ordered steps instead of a graded challenge.
  - Each step has a short explanation, the exact config per device (copy buttons), verification commands with what
    good output looks like, and **Check this step** (live checks plus config checks).
  - A progress bar with free back/forward movement and a final **summary** (what you built, the complete config per device).
  - **Apply this step for me** types the step's config over the CML console. It sends `exit` when the indentation
    leaves a sub-mode (and after bare NX-OS mode commands), starts every top-level block from global config mode, and
    stops at the first rejected line. CLI: `encorlab step <lab> [N] [--check|--apply]`.
  - Walkthroughs have no *Break my lab* or exam mode (the API refuses both). They are marked *walkthrough* in the list,
    courses and library, count as *completed* (not scored) and have their own section on the Progress page, outside
    mastery, solved-lab counts and streaks.
- **Built-in lab `18-evpn-vxlan`: BGP EVPN VXLAN spine-and-leaf walkthrough** on Nexus 9000v (`nxosv9000`, NX-OS 10.5).
  - 2 spines, 2 leaves and 4 IOS hosts (8 nodes).
  - Steps: OSPF underlay over /31s, NX-OS features, iBGP `l2vpn evpn` with the spines as route reflectors,
    VLAN 10/20 mapped to L2VNI 10010/10020, NVE with BGP ingress replication, then same-VLAN pings between the leaves
    verified with type-2/type-3 routes, NVE peers and MAC learning over the tunnel. An optional last step adds the
    L3VNI with symmetric IRB and the anycast gateway (type-5 routes).
  - Needs about 52 GB of CML RAM and 12 vCPUs.
- **New course "Data center: VXLAN EVPN fabrics"** (`data-center.encorcourse` in the online library).
- **Node definitions:** a lab node can set `definition: nxosv9000`. Such nodes use literal `Ethernet1/1-1/4` names
  (`mgmt0` stays unconnected) and get an NX-OS day-0 config with your device logins. The build checks that the server
  has the definition and waits at least 25 minutes for NX-OS to boot. The console login also handles NX-OS `login:`.
- **RAM estimate on every lab**, from the CML 2.9 node-definition defaults (iol-xe 1 GB, iosv 0.5 GB, nxosv9000 12 GB,
  cat9000v 18 GB, …) or the lab's new optional `ram_gb:` field.
  - Labs at or above a threshold (*Settings > Lab options*, default 16 GB, `ENCOR_RAM_HEAVY_GB`) get a red
    **RAM heavy · ~N GB** tag, with text as well as color. Its tooltip explains the estimate.
  - The tag shows in the lab list, on the lab page, in courses, in the online library (`ram_gb` and `type` in
    `labs/index.json`) and in `encorlab list`.
  - **Build** now opens a confirmation box with the RAM estimate first.
- Lab authoring guide and AI prompt: walkthrough labs, node definitions, NX-OS regex and ping tips, `ram_gb` and RAM guidance.
### Changed
- The lab JSON schema: `checks` is optional (walkthroughs keep their checks in `steps`), and `type`, `steps`, `ram_gb`
  and `nodes[].definition` are new.
- `validate`/`pack` check literal interface names per device (NX-OS names on `definition` nodes, placeholders
  elsewhere) and grade every walkthrough step offline.
- The runtime is unchanged (RUNTIME_VERSION 1), so 1.7.x and 1.8.x update to 1.9.0 as a normal patch.

## [1.8.1] - 2026-10-19
### Added
- **MIT License** (`LICENSE`, Copyright (c) 2026 Dylan Vaughan (Specops13)).
  - `pyproject.toml` declares `license = "MIT"` (SPDX, with `license-files`).
  - The README has a license section and badge.
  - The .deb's `copyright` file is now DEP-5 with MIT for the app and a pointer to the third-party notices for the
    bundled runtime.
- **`THIRD-PARTY-NOTICES.txt`** in the Windows zip, the Linux tar.gz and the .deb (`/usr/share/doc/encorlab/`, next
  to `LICENSE.txt`). It is generated at build time by `packaging/third_party_notices.py` from PyInstaller's tables of
  what was actually bundled: every component with its version, license, project page and full license text (CPython,
  paramiko, virl2_client, FastAPI, …).
- **License check:** the build stops if a bundled package has an unknown license, no license text, or a strong
  copyleft license (GPL/AGPL).
### Changed
- The build requires setuptools 77 or newer (for SPDX license expressions). The runtime is unchanged
  (RUNTIME_VERSION 1), so 1.7.x and 1.8.0 update to 1.8.1 as a normal patch.

## [1.8.0] - 2026-10-19
### Added
- **Debian package** `encorlab_1.8.0_amd64.deb` (Debian 10+, Ubuntu 20.04+). Install it with
  `sudo apt install ./encorlab_1.8.0_amd64.deb`. It is the same frozen build as the Linux tar.gz.
  - **Layout:** the app is in `/opt/encorlab`, with the `encorlab` command in `/usr/bin`, a menu entry
    (*ENCOR Lab Builder*, hicolor icons from 16 to 256 px) and a man page.
  - **Launch:** like the exe, the menu entry opens a terminal with the server and your browser. Starting it again only
    opens the browser on the running copy.
  - **Dependencies:** `libc6 (>= 2.28)`, `libgcc-s1 | libgcc1` and `zlib1g`. `xdg-utils` is recommended.
  - **Maintainer scripts:** they refresh the desktop and icon caches. `apt remove` and `apt purge` never delete
    `~/.config/encorlab`.
  - **Checks:** the package is clean under `lintian --pedantic` and `desktop-file-validate`.
- **Auto-updates for the .deb, exactly like the exe:** patches install into `~/.config/encorlab/app/<version>` and
  never into `/opt`, so no root is needed. The prompt, the waiting while work is busy, and rollback are unchanged.
  - **Install type:** the app detects it (`install-type` marker: deb / linux-tar / windows-zip / source).
    `update-status` and `/api/update/status` show it.
  - **Full download needed:** the banner now links the right file for the install type: the `.deb` with its
    `sudo apt install ./…` command, the tar.gz, or the Windows zip.
- **Upgrades:** `apt install ./newer.deb` upgrades cleanly over an older package. An installed patch that is newer than
  the package's built-in copy keeps running; a newer package wins over an older patch. Unit tests and the chroot test
  cover this.
- **Build and test:** `packaging/build_deb.py` builds the .deb from the Linux tar.gz (`dpkg-deb --root-owner-group`,
  reproducible, no root needed). `packaging/deb_chroot_test.sh` runs an end-to-end test in a clean Debian 12 chroot
  (install, validate, launch, single instance, smoke test with patches and auto-update as a normal user, upgrades,
  remove/purge). CI builds and lints the .deb, installs and smoke-tests it in a `debian:12` container, and releases
  it with the other files in `SHA256SUMS.txt`.
- `tests/test_deb.py`: install-type detection, the asset for each install type, the deb banner, patch-vs-package
  precedence, the package layout, metadata and permissions, and the maintainer scripts.
### Unchanged
- The runtime (RUNTIME_VERSION 1). 1.7.0 installs update to 1.8.0 as a patch through the normal prompt.

## [1.7.0] - 2026-10-18
### Added
- **Automatic updates that ask first** (packaged app, Windows and Linux):
  - **Background check:** a background task checks GitHub Releases about 45 s after start and then every 6 hours,
    using ETag conditional requests. If a newer release has a patch for this runtime, the task downloads it and
    verifies it (SHA256SUMS, manifest hashes, safe paths, version, `min_runtime`), then keeps it in
    `<data>/updates/staged/` without installing it.
  - **Prompt:** a non-modal card says *ENCOR Lab x.y.z is ready* with *Update now / Later / Skip this version* and
    links to the release notes and the changelog.
  - **Update now:** installs the patch, restarts on the same port and reconnects the page, which then shows the
    toast *Updated to x.y.z*. If a lab build, grading run, live test, snapshot or restore, fault injection or exam is
    running, it waits until that finishes (the card says what it waits for, and *Cancel* is available). New work is
    refused for the few seconds of installing and restarting.
  - **Later** hides the card until the next launch or for 4 hours. **Skip** stops offering that version.
  - **Rollback:** rollback stays as before (automatic when a new version cannot start, plus manual). A version that
    was rolled back is never offered again automatically, only by *Check for updates now*.
  - **Full download needed:** if the release needs a newer runtime (or has no patch), nothing is patched; a
    dismissible banner links the full download instead.
  - **Quiet failures:** network errors, rate limits and bad downloads are logged to `<data>/updates/update.log` and
    retried with exponential backoff (15 min up to 12 h, or GitHub's rate-limit reset time). No popups.
  - **API:** `/api/update/auto`, `/api/update/check`, `/api/update/apply`, `/api/update/cancel`, `/api/update/later`,
    `/api/update/skip`, `/api/update/dismiss-full`, `/api/update/ack`.
- **Testing:** `packaging/fake_release.py` serves a fake GitHub release on 127.0.0.1 (`ENCOR_UPDATE_URL`; plain http
  is accepted only for loopback). The smoke test's `--auto-update-test` runs the whole automatic flow on both frozen
  builds.
### Changed
- **Default on:** *Check for updates automatically* is now on by default and switches the background updater on and
  off. Settings files from 1.6.x and older (which always stored the old default `false`) are migrated to on once.
  `settings.json` now records `_format: 2`, so a later opt-out is kept.
- **Removed:** the page's once-a-day client-side check and the separate *Install update* button. *Check for updates
  now* downloads, verifies and shows the prompt. `ENCORLab update-install` and `/api/update/install` are unchanged.
- **From source:** automatic checks are disabled; *Check for updates now* only reports and suggests `git pull`.
### Upgrading
- 1.7.0 uses the same runtime (1) as 1.6.0. In 1.6.0, use *Settings > Updates > Check for updates now > Install
  update > Restart now* once; 1.7.0 then updates itself (with the prompt). From 1.5.x, download the full release.

## [1.6.0] - 2026-10-18
### Added
- **Multicast labs**. Both run on IOL or IOSv routers, with routers acting as the
  source and receiver hosts:
  - `14-multicast-pim-sm` (5 nodes, ENCOR 3.3.d): `ip multicast-routing`, PIM sparse mode on every path interface, a
    static RP, an IGMP join, shared tree vs. shortest-path tree, and the RPF check.
  - `15-multicast-bsr-ssm` (6 nodes, 3.3.d): BSR election with two candidate BSRs and two candidate RPs, IGMPv3 at the
    receiver edge, and an SSM channel `(10.1.1.10, 232.1.1.1)` that needs no RP.
  - Live checks use `show ip pim neighbor`, `show ip pim rp mapping`, `show ip pim bsr-router`, `show ip igmp groups`,
    `show ip igmp interface`, `show ip mroute` and a ping to the group; a fault check uses `show ip rpf`. Each lab has
    config checks, a solution summary, 3 hints and 3 *Break my lab* faults. The recorded outputs are synthesized from
    Cisco documentation and are not verified on real hardware.
- **MPLS labs** (18 built-in labs, 54 faults), on IOL or IOSv:
  - `16-mpls-ldp` (4 nodes, 2.2): LDP on the core links, `mpls ldp router-id Loopback0 force` (with an unadvertised
    Loopback1 that shows why), label bindings, the LFIB, penultimate-hop popping and an LSP ping (`ping mpls ipv4`).
  - `17-mpls-l3vpn` (5 nodes, advanced, 2.2 / 2.2.a): VRF CUST-A with RD and route targets, moving the CE link into the
    VRF, iBGP VPNv4 between the PE loopbacks with extended communities, and eBGP to the CEs inside the VRF.
  - Faults include an unreachable LDP router ID, a one-sided LDP MD5 password, a wrong import route target, and a
    broken LSP under healthy BGP. The recorded outputs are synthesized and not verified on real hardware.
- **Course "Multicast and MPLS track"** (`encor-multicast-mpls`) in the online library: labs 14, 15, 08-vrf-lite, 16 and 17.
- Standalone `.encorlab` packs of the four new labs, with their own ids, attached to the release. They import into 1.5.x.
- **Patch updates instead of full downloads.** The packaged app is split into a frozen runtime (exe, Python, libraries,
  boot loader) and the app code, which ships as plain files in `_internal/appcode/`. *Settings > Updates > Install update*
  downloads only `encorlab-patch-<version>.zip` (about 0.25 MB versus 30+ MB), verifies it, and installs it into the
  data folder (`app/<version>/`). *Restart now* restarts on the same port. The patch is verified against the release's
  `SHA256SUMS.txt`, every file against `manifest.json` (no extra files, no paths outside `encorlab/`), and its version
  and `min_runtime` are checked. If a release needs a newer runtime, the app says *Full download needed* and links it.
  - Rollback: automatic if a new version fails to import or exits before its web UI starts (it is marked good once
    the UI is up), and manual with *Roll back*. The current and the previous patch are kept.
  - CLI: `update-status`, `update-install [--file] [--sha256]`, `update-rollback`.
    API: `/api/update/status|install|rollback|restart`.
  - Build: `packaging/build_patch.py` makes a deterministic patch. `packaging/runtime.lock.json` fingerprints the
    runtime, and CI fails if the runtime changes without a `RUNTIME_VERSION` bump. CI publishes the patch and lists it
    in `SHA256SUMS.txt`.
  - The bundled app code is byte-compiled with hash-checked `.pyc`. The smoke test (`--patch-test`) exercises install,
    a patched UI start, rollback, broken-patch fallback and runtime gating on the frozen build.
  - 1.6.0 is the first patchable runtime: coming from 1.5.x needs one full download.
- The offline config merge (used to validate faults) knows `ip igmp version`, `ip pim rp-candidate`, `ip pim bsr-candidate`,
  `ip pim ssm`, `mpls ldp router-id`, `mpls label protocol` and `rd` as single-value lines.

## [1.5.0] - 2026-10-18
### Added
- **Three new built-in labs** (14 in total), each with a solution summary, 3 progressive hints and 3 faults:
  `11-ipsla-tracking` (IP SLA ICMP probe + object tracking driving the default route and an HSRP priority decrement;
  4.4 / 3.3.c), `12-pbr` (source-based policy routing to a second ISP with ACL + route-map + `ip policy`; 3.2.d) and
  `13-redistribution` (two-point mutual OSPF/EIGRP redistribution with route-map tagging and tag filtering; 3.2.a / 3.2.b).
  All use plain IOL/IOSv routers. A multicast (PIM) lab was not added because its output could not be verified on IOL.
- The *ENCOR routing track* course now ends with the PBR and redistribution labs.
- **Break my lab (fault practice).** Each built-in lab has 3 predefined faults (42 in total). *Break my lab* rebuilds the
  working lab with a random fault (not one used recently) and shows a symptom-only trouble ticket. Check grades the lab
  checks plus fault-specific checks; when it passes, you see the root cause and fix. Fault-specific hints,
  *Reveal the answer*, *End fault practice*, and Reset re-applies the same broken config.
  CLI: `break <lab> [--fault ID]`, `fault <lab> [--reveal|--end]`. History marks fault attempts.
- **Progress dashboard** (Progress page, `progress` CLI, `GET /api/progress`): mastery per ENCOR v1.2 domain (weighted)
  and blueprint item, weakest topics, streak, time spent, most-failed checks and 30-day activity. Each Check now records
  the lab timer value and whether the answer had been revealed.
- **Lab library and courses:** a *Library & courses* panel and `library` / `course` CLI commands. Install lab packs and
  `.encorcourse` courses (ordered study tracks) from the repo's new `labs/` folder or any https URL, with sha256/size
  verification, an https-only policy and a 20 MB limit. Courses track solved/total with *Continue* and a course filter.
  `packaging/build_library.py` builds `labs/` reproducibly; two courses ship (OSPF Mastery, ENCOR routing track).
- **Console links:** a *Consoles* section per built lab with *Open lab in CML* (`https://<cml>/lab/<id>`) and a copyable
  console server command per node (`ssh -t user@host "open /<lab>/<node>/0"`, custom port supported). Also `console <lab>`
  in the CLI and `cml_lab_url` / `consoles` in `GET /api/labs/{id}/status`.
- **Update check:** *More > Check for updates*, *Settings > Updates* and `update-check` compare your version with the
  latest GitHub release and link to it. The optional daily automatic check (`check_updates`) is off by default.
- **Exam mode:** a timed one-shot attempt (*Exam mode* button, `exam` CLI command). It has a countdown with
  auto-submit, the solution, check hints, source and export withheld, and hints either disabled or penalized (the server
  counts them, not the client). A late submission scores 0%. The score report (raw score, penalty, time, pass/fail
  against an 80% target) is stored in the history and counted by the progress dashboard.
- **Config snapshots:** save the running configs of a built lab (CML config extraction) and restore them (stop, wipe,
  reboot with the saved day-0 configs). View or download them as `.cfg`, up to 20 per lab, using the *Config snapshots*
  section, the `snapshot` CLI command or `/api/labs/{id}/snapshots`. Show-run banners are stripped, and restoring onto
  the other image platform is refused.
- **Printable reports:** lab report (latest check per objective, exam/fault result, solution summary, attempt history,
  optional command output) and progress report, as print-ready HTML (*Print report* buttons, `/report/labs/{id}`,
  `/report/progress`, `report` CLI command). The latest full check result per lab is now kept in `reports/` in the data folder.
- Lab files can define `faults:`. The validator applies each fault offline with an IOS-style config merge and requires
  that it is detected and fixable.
### Changed
- Blueprint tags follow the current **350-401 ENCOR v1.2** exam topics: HSRP is 3.3.c, NAT/ACL is 3.3.b + 5.2.a,
  NTP/Syslog/SNMP/IP SLA is 3.3.a + 4.1 + 4.4, GRE/IPsec is 2.2.b. The validator warns about unknown blueprint items.
### Fixed
- 07-acl-nat: the BLOCK-TELNET config check now accepts the sequence numbers IOS-XE shows in named ACLs (`10 deny ...`).

## [1.4.0] - 2026-10-17
### Added
- **Solution summary.** New `solution_summary` lab field (Markdown: root cause, the exact fix per device, why it works).
  It appears automatically when a Check scores 100%. Below 100%, **Reveal solution** (after a confirm) shows it together
  with the solution config per device. Labs without one get a summary generated from their solution config.
- **Progressive hints.** A **Hint** button next to Check reveals the next hint in order ("Hint 2 of 3").
  Hints come from the new lab-level `hints` list, or from the per-check hints. Revealed hints are remembered per lab in the
  browser and cleared on Reset. The results history records the hints used.
- CLI: `solution <lab>`, `hint <lab> [N]`, `check --hints-used N`. `check` prints the solution summary at 100%.
- Solution summaries and hints for all 11 built-in labs and both example packs.
- New example pack **troubleshoot-ospf-7node**: a trouble ticket on a 7-router multi-area OSPF network with one planted fault.
- **Ready-to-run builds** (PyInstaller one-folder) for Windows x64 and Linux x64 (glibc 2.28+), with a desktop launcher.
  The launcher uses a free port (8765 by default), opens the browser, detects an already running copy and passes CLI commands through.
  Build scripts live in `packaging/`, and a CI workflow builds and smoke-tests both bundles.
- UI version check: a banner appears if a cached script is out of date or the app was updated while the tab was open.
- The validator warns when a lab has no `solution_summary` or no hints. The authoring guide and AI prompt now require a summary.
### Fixed
- Markdown rendering: consecutive lines are joined into one paragraph (soft wrap) instead of one paragraph per line.

## [1.3.1]
### Fixed
- After upgrading, a stale browser cache could leave the UI with dead buttons and no labs.
  Asset URLs are now versioned (`?v=<version>`) and every response is sent with `Cache-Control: no-cache`.
### Changed
- The frontend is more resilient: each startup step runs separately, a visible error banner reports failed requests
  and script errors, and `/api/labs` reports a broken lab instead of failing as a whole.
- Explicit MIME types for static files and UTF-8 everywhere (Windows).
- README: Diagnostics section (hard refresh, F12 console).

## [1.3.0]
### Added
- Help icons with tooltips for every control: hover delay, keyboard focus, Esc to close, dark mode.
  All help text lives in `help.json`, and a test makes sure every interactive control has help. A *Show help icons* setting turns them off.
### Fixed
- Raw `%if0%` placeholders no longer appear anywhere a user can see them (task preview, grading results).

## [1.2.x and earlier]
- 1.2.0: the 10 staged labs are enabled, each with live and config checks.
  Also added user labs (import/export `.encorlab` packs, drag-and-drop), the Lab builder (form + YAML, check templates,
  import from CML, offline and live tests), strict offline validation, and the AI prompt plus an optional OpenAI-compatible generator.
- Example pack `ospf-multiarea-stub`. Easier import (drop files anywhere, replace prompt).
- Launchers pick a supported Python (3.10-3.13) and recreate an unsupported `.venv`.
- Two grading modes (live over the CML console server, config over HTTPS) with *auto* fallback, and per-check modes.
- First release: the `eigrp-basic` lab, CML 2.9 build/check/reset/destroy, web UI and CLI, IOL default with IOSv option.

[1.4.0]: https://github.com/Specops13/encore-lab-app/releases/tag/v1.4.0
