# ENCOR Lab Builder

**Build CCNP ENCOR (350-401) practice labs in Cisco Modeling Labs (CML) 2.9 and auto-grade your solutions.**

[![Latest release](https://img.shields.io/github/v/release/Specops13/encore-lab-app)](https://github.com/Specops13/encore-lab-app/releases/latest)
![Python 3.10-3.13](https://img.shields.io/badge/python-3.10--3.13-blue)
![Windows 11 | Debian/Ubuntu](https://img.shields.io/badge/platform-Windows%2011%20%7C%20Debian%2FUbuntu-lightgrey)

Pick a lab and click **Build**: the topology is imported into your CML server, booted and pre-configured.
Solve the task on the device consoles, then click **Check**. The app grades you with read-only `show`/`ping`
commands (live mode) or by reading the running configs over the CML API (config mode). It tells you what passed,
what failed and why. Progressive hints and a solution summary help you learn instead of just getting a score.
It runs as a local web UI on `127.0.0.1` (plus an equivalent CLI). Device checks go through the **CML console
server**, so your PC only needs to reach the CML controller, not the lab devices.

![Lab page with progressive hints](docs/images/lab-hints.png)

## Contents
- [Features](#features)
- [Screenshots](#screenshots)
- [Quick start (ready-to-run download)](#quick-start-ready-to-run-download)
- [Updating (small patches instead of a full download)](#updating-small-patches-instead-of-a-full-download)
- [Running from source](#running-from-source)
- [CML requirements](#cml-requirements)
- [Using it](#using-it)
- [Grading modes](#grading-modes)
- [Creating and importing labs](#creating-and-importing-labs)
- [Configuration](#configuration)
- [Troubleshooting and diagnostics](#troubleshooting-and-diagnostics)
- [Building the executables](#building-the-executables)
- [Project layout](#project-layout)
- [Development / tests](#development--tests)
- [Version and changelog](#version-and-changelog)

## Features
- **18 built-in labs** covering ENCOR blueprint topics: EIGRP basic, VLAN/802.1Q/Rapid PVST+, EtherChannel (LACP/PAgP),
  OSPFv2 multi-area/stub/summarization, EIGRP named mode with authentication and stub, eBGP/iBGP with next-hop-self,
  HSRPv2 with tracking, ACL/PAT/static NAT, VRF-lite, GRE over IPsec with OSPF, NTP/Syslog/SNMPv3/IP SLA,
  HSRP failover driven by IP SLA object tracking, policy-based routing, mutual OSPF/EIGRP redistribution with route tags,
  **IP multicast** (PIM sparse mode with a static RP, BSR RP election, IGMPv3 and SSM) and **MPLS** (LDP core, and an
  MPLS L3VPN with VRFs and MP-BGP VPNv4). See [Multicast and MPLS labs](#multicast-and-mpls-labs).
- **One-click lifecycle in CML:** Build (import + start + wait for boot), Check, Reset (back to the starting configs), Destroy.
  It only ever touches labs titled `ENCOR-…`.
- **Two grading modes:** *live* (real adjacencies, routes, pings over the console server) and *config* (HTTPS only).
  *Auto* uses live when it can and falls back to config.
- **Break my lab (fault practice):** every built-in lab ships with 3 predefined faults (54 in total). One click rebuilds
  the working lab with a random fault and gives you a symptom-only trouble ticket, so you get unlimited troubleshooting practice.
- **Exam mode:** a timed, one-shot attempt with a countdown, the solution withheld, and hints disabled or costing
  points. *Submit exam* (or the timer running out) grades once and shows a score report (raw score, hint penalty,
  time used, pass/fail against an 80% target).
- **Printable reports:** a lab report (latest check per objective, exam result, solution summary, attempt history) and a
  progress report (domains, weakest topics, all labs) as clean pages. Print them or save them as PDF from the browser.
- **Config snapshots:** save the running configs of a built lab (over the CML API) and restore them later. Restore
  stops, wipes and reboots the lab with the saved configs. View or download snapshots as text.
- **Progress dashboard:** mastery per ENCOR 350-401 v1.2 exam domain (with the official weights) and per blueprint item,
  your weakest topics with links to the labs that train them, daily streak, time spent, most-failed checks and recent activity.
- **Console links:** once a lab is built, open it in the CML Workbench with one click, or copy a ready-to-paste
  console server command (`ssh -t user@cml "open /ENCOR-<lab>/R1/0"`) for any node.
- **Learning aids:** a **Hint** button with progressive hints ("Hint 2 of 3"), remembered per lab and cleared on Reset.
  A **Solution summary** (root cause, exact fix per device, why it works) appears automatically at 100%.
  Below 100% you can open it with **Reveal solution**, after a confirm.
  You also get a per-lab timer and a results history that records the hints you used.
- **Lab library and courses:** browse the online library (the repo's [`labs/`](labs/) folder) and install lab packs or
  whole **courses** (ordered study tracks of labs, `.encorcourse`) with one click. Every download is checked against the
  sha256 in the index. Courses show your progress and a *Continue* button for the next unsolved lab.
- **Bring your own labs:** import `.encorlab` packs or `.yaml` files by drag-and-drop, edit them in the **Lab builder**
  (form + YAML with live validation and check templates), import a topology from CML, or generate labs with any AI chatbot
  using the built-in prompt.
- **Offline validation:** each lab's reference solution must score 100% and the starting config must fail, on both IOL and IOSv.
  Recorded outputs let the live checks be tested without a CML server.
- **IOL by default** (light enough for a 20-node CML Personal license), IOSv optional. Interface names come from `%if0%`
  placeholders, so one lab file works on both.
- **Safe by design:** loopback-only UI, read-only checks, secrets kept in memory or the OS keyring and never written to
  settings.json or logs. TLS verification stays on.
- **Update check and patch updates:** *More > Check for updates* (or *Settings > Updates*) asks GitHub Releases whether a
  newer version exists. From 1.6.0 the packaged app can **Install update**: it downloads only the app-code patch
  (about 0.25 MB instead of 30+ MB), verifies it, and you restart. The automatic daily check is **off by default**.
- **Ready-to-run downloads** for Windows 11 and Linux (no Python needed), plus a `?` help tooltip on every control and a dark mode.

## Screenshots
| | |
|---|---|
| ![Lab catalog and task](docs/images/catalog.png) | ![Solution summary after a 100% check](docs/images/solved-summary.png) |
| Lab catalog, task and actions | Solution summary, shown automatically at 100% |
| ![Reveal solution below 100%](docs/images/results-reveal.png) | ![Lab builder](docs/images/builder.png) |
| *Reveal solution* (after a confirm): summary plus the config per device | Lab builder with live validation |
| ![Settings in dark mode](docs/images/settings-dark.png) | ![Progressive hints](docs/images/lab-hints.png) |
| Settings: CML connection, console server, grading mode (dark mode) | Progressive hints on a troubleshooting lab |

## Quick start (ready-to-run download)
Download from **[Releases](https://github.com/Specops13/encore-lab-app/releases/latest)**. You don't need Python.

| Download | Start it |
|---|---|
| `ENCORLab-<version>-windows-x64.zip` (Windows 10/11 x64) | Unzip anywhere (e.g. `Documents\ENCORLab`) and double-click **ENCORLab.exe** |
| `ENCORLab-<version>-linux-x64.tar.gz` (glibc 2.28+: Debian 10+, Ubuntu 20.04+) | `tar xzf ENCORLab-*.tar.gz && ./ENCORLab-*/ENCORLab` (optional: `./install-desktop-entry.sh` adds a menu entry) |

- A small console window opens and your default browser shows the app at http://127.0.0.1:8765. If the port is busy, the next free port is used and the window shows the real address.
- Starting it again while it runs just opens the browser on the running copy.
- **Quit:** close the console window or press Ctrl+C.
- **Your data stays outside the app folder,** in `%APPDATA%\encorlab` or `~/.config/encorlab`. That covers settings, imported labs, history and installed updates. To update, use *Settings > Updates > Install update* (see [Updating](#updating-small-patches-instead-of-a-full-download)), or delete the old app folder and unzip the new one.
- The bundle includes `example-packs/` (drag them onto the Labs page), `docs/` and this README.
- The command line works too: `ENCORLab list`, `ENCORLab check <lab>`, `ENCORLab --port 9000`, `ENCORLab --no-browser`.
- **Windows SmartScreen:** the exe is not code-signed, so the first start may show "Windows protected your PC". Click *More info* > *Run anyway*.
  You can also right-click the downloaded zip, choose *Properties* > *Unblock*, then extract it. Check the download against `SHA256SUMS.txt` from the release.

Then open **Settings**, enter your CML URL and credentials, pick a lab and click **Build**.

## Updating (small patches instead of a full download)
Since 1.6.0 the download is split in two parts:

- **The runtime:** the exe, Python and the libraries in `_internal/`. It only changes with a full download.
- **The app code:** the `encorlab` package. It ships in `_internal/appcode/` and can be replaced by a small patch
  (`encorlab-patch-<version>.zip`, about 0.25 MB, attached to each release).

**How to update** (Windows 11 and Linux, all in the GUI; every button has a `?` tooltip):
1. *Settings > Updates > Check now* (or *More > Check for updates*). If a newer release has a patch, an **Install update** button appears.
2. **Install update** downloads the patch and verifies it before anything is installed:
   - the zip's SHA-256 must match the release's `SHA256SUMS.txt`;
   - every file must match the SHA-256 in the patch's `manifest.json`, with no extra or missing files and no paths outside `encorlab/`;
   - the version must match the release, and the patch's `min_runtime` must not be newer than your runtime.

   The patch is then unpacked into your data folder (`%APPDATA%\encorlab\app\<version>` or
   `~/.config/encorlab/app/<version>`). The app folder itself is never modified.
3. **Restart now** restarts the app on the same port, and the page reconnects by itself. Closing and starting the app works too.

**Safety net:**
- **Automatic rollback:** a new version counts as good once its web UI has started. If it fails to import, exits with an
  error before the UI starts, or crashes before its UI comes up, the next start falls back to the previous version
  (or the built-in copy) and *Settings > Updates* shows why.
- **Manual rollback:** *Roll back* returns to the version you used before (or the built-in copy) from the next restart.
  Only the current and the previous patch are kept.
- **Newer full download wins:** if you unzip a full release that is newer than your installed patch, its built-in code is used.

**When a full download is needed:** if a release changes the runtime (a new Python, a new or upgraded library, or a
change to the launcher), its patch declares a higher `min_runtime`. *Install update* then says **Full download needed**
and links the release page. Your data is kept. 1.6.0 is the first patchable runtime, so **coming from 1.5.x you need one
full download of 1.6.0**. After that, patches work.

**Command line:** `ENCORLab update-status`, `ENCORLab update-install` (latest release),
`ENCORLab update-install --file encorlab-patch-<v>.zip [--sha256 …]` (offline) and `ENCORLab update-rollback`.

> **Security note:** the checksums come from the same GitHub release as the patch. This proves the download is complete
> and unmodified in transit, but it is not a code signature: whoever can publish releases on this repo can publish a
> patch. The app never installs anything on its own; it only acts when you click *Install update*.
> When you run from source (`run.sh` / `pip install -e .`), use `git pull` instead; the patch buttons are disabled there.

## Running from source
Needs Python **3.10 to 3.13** (3.13 recommended). Python 3.14+ is not supported yet: some dependencies have no prebuilt wheels for it.

**Windows 11** (python.org 64-bit installer, with the "py launcher" option checked):
```powershell
git clone https://github.com/Specops13/encore-lab-app.git
cd encore-lab-app
copy .env.example .env     # optional: CML_URL / CML_USERNAME
.\run.bat                  # first run creates .venv and installs everything, then opens the UI
```

**Debian / Ubuntu:**
```bash
sudo apt install python3 python3-venv git
git clone https://github.com/Specops13/encore-lab-app.git && cd encore-lab-app
cp .env.example .env       # optional
./run.sh                   # web UI on http://127.0.0.1:8765
```
Manual alternative: `python3 -m venv .venv && .venv/bin/pip install -e . && .venv/bin/python -m encorlab web`.
`run.bat <command>` / `./run.sh <command>` runs any CLI command (see [Using it](#using-it)).

## CML requirements
- **CML 2.9.x**. The client library is pinned to `virl2_client>=2.9.0,<2.10` to match the controller. `doctor` warns on other versions.
- **Images:** IOL (`iol-xe`) and IOL-L2 (`ioll2-xe`) by default, or IOSv / IOSvL2 (*Settings > Device images*).
  Labs use 2-7 nodes. A node limit (default 20, the CML Personal license) is enforced before starting a lab.
- **From your PC:** HTTPS to the CML URL, for the API and config mode. Your own CA or Let's Encrypt certificate works with TLS verification on.
- **For live checks:** SSH to the **CML console server**, by default the CML host on **port 22**.
  You can set a separate *Console server FQDN* and port, for example behind a TCP passthrough proxy (see below).
  Without it, config mode still works over HTTPS only.
- A CML user that can create labs. Labs are created as `ENCOR-<lab id>`.

### Console access and your reverse proxy
Live checks open `ssh <cml-user>@<console host>:<port>` and run `open /ENCOR-<lab>/<node>/0` on the CML console server.
They then run only read-only `show` and `ping` commands. The console server is set separately from the CML URL:
Settings field **"Console server FQDN (port 22 proxy)"** plus **port** (default 22), or `CML_CONSOLE_HOST` / `CML_CONSOLE_PORT` in `.env`.
If you put a proxy in front of port 22, it **must be a TCP/stream passthrough** (nginx `stream { server { listen 22; proxy_pass <cml>:22; } }`, HAProxy `mode tcp`).
An HTTP/HTTPS reverse proxy cannot carry SSH. `doctor` opens a TCP connection to the console server and checks for an `SSH-` banner.
If it gets an HTTP response, it tells you the proxy is not TCP passthrough.
The first connection accepts the server's host key and logs a warning.

## Using it
1. **Settings**: enter the CML URL, username and password. TLS verification stays **On**.
   - The password is kept in memory only. Tick "Remember password in OS keyring" to store it in Windows Credential Manager or the Linux Secret Service.
   - Non-secret settings are saved to `settings.json` in your data folder.
   - Set *Console server host* if SSH port 22 isn't reachable at the URL's host name.
2. **Labs**: pick a lab and click **Build**. It imports the topology as `ENCOR-<lab>`, starts it and waits until all nodes are BOOTED.
3. Open the device consoles: the lab's **Consoles** section has an *Open lab in CML* link and a copyable
   `ssh -t <user>@<console host> "open /ENCOR-<lab>/<node>/0"` command per node (Windows 11 has `ssh` built in).
   Solve the task, then click **Check**. You get pass/fail per check, with details and the raw output.
4. Stuck? Click **Hint** for the next hint. At 100% the **Solution summary** appears. Below 100%, **Reveal solution** shows it after a confirm.
5. **Reset** stops the lab, wipes it and restarts it with the original configs (it also clears revealed hints). **Destroy** stops, wipes and deletes the lab.
6. Done with a lab? Click **Break my lab** for troubleshooting practice, or **Exam mode** for a timed attempt (see below).

A timer starts on Build and stops when the lab is solved, and each lab keeps a results history.
Small **?** icons explain each field. Turn them off with *Settings > Show help icons*; all help text is in `encorlab/web/static/help.json`.
◐ toggles dark mode.

CLI equivalents (`ENCORLab <cmd>` for the download; `run.bat <cmd>` / `./run.sh <cmd>` / `python -m encorlab <cmd>` from source):

| Command | What it does |
|---|---|
| `list`, `task <lab>`, `version` | catalog, task text, version |
| `doctor` | tests CML login, images, node budget and the console server |
| `build <lab> [--rebuild]`, `check <lab> [--mode auto\|live\|config] [--json] [--hints-used N]`, `reset <lab>`, `destroy <lab>` | lab lifecycle (`check` prints the solution summary at 100%) |
| `hint <lab> [N]`, `solution <lab>` | progressive hint N of M; solution summary + config (spoilers) |
| `break <lab> [--fault ID]`, `fault <lab> [--reveal\|--end]` | Break my lab: rebuild with a random fault and print the ticket; show/reveal/end the active fault |
| `console <lab>` | CML web link and console server `ssh` commands for each node |
| `update-check` | ask GitHub Releases whether a newer version exists (nothing is installed) |
| `update-status`, `update-install [--file patch.zip] [--sha256 …]`, `update-rollback` | packaged app: show the running app code, install the latest (or a downloaded) patch, roll back |
| `exam <lab> --start [--minutes N] [--hints penalty\|off] [--penalty P]`, `exam <lab> [--abort]` | exam mode: start, status, abort (submit with `check`; `hint` costs points) |
| `snapshot <lab> [--save NAME] [--restore NAME] [--show NAME] [--delete NAME]` | config snapshots: list, save, restore, print, delete |
| `report [<lab>] [-o file.html] [--outputs] [--name "Your Name"]` | printable HTML report of a lab (or of your progress); print or save as PDF |
| `history <lab>` | your past scores (with hints used) |
| `progress [--json]` | progress dashboard: mastery per exam domain, streak, time spent, weakest topics |
| `library list` / `library install <file or https URL> [--sha256 …]` | browse / install from the online lab library |
| `course list` / `course build <dir> [-o file]` / `course delete <id> [--labs]` | courses: progress, build a `.encorcourse`, remove |
| `import <file> [--replace]`, `export <lab> [-o f.encorlab] [--cml-yaml]`, `delete <lab> -y` | manage your labs |
| `validate [paths…]`, `pack <folder-or-yaml> [-o x.encorlab]` | offline test (solution 100%, starting config 0%); strict validate + write a shareable pack |
| `test-live <lab> [--keep]` | builds `ENCOR-TEST-<lab>` with the solution applied, grades it, deletes it |
| `schema [-o f]`, `prompt ["request"]`, `docs` | JSON Schema, AI prompt, regenerate `docs/` |
| `save-password`, `web [--no-open]` | keyring, web UI |

### Multicast and MPLS labs
These labs need nothing beyond the standard CML 2.9 images. Every node is a plain router (`iol-xe` by default, or
`iosv` with *Settings > Device images*), so the receivers and sources are routers acting as hosts: a receiver joins
with `ip igmp join-group`, and a source pings the group address. Both images use `ip multicast-routing` (the
`distributed` keyword is rejected on IOL).

| Lab | Topic | Nodes | Live checks use |
|---|---|---|---|
| `14-multicast-pim-sm` | `ip multicast-routing`, PIM-SM on every path interface, static RP, IGMP join, shared tree vs. SPT, RPF | 5 (SRC, R1-R3, RCV) | `show ip pim neighbor`, `show ip pim rp mapping`, `show ip igmp groups`, `ping 239.1.1.1`, `show ip mroute`, `show ip rpf` (fault) |
| `15-multicast-bsr-ssm` | BSR election (higher priority wins) vs. C-RP election (lower wins), IGMPv3, SSM `(S,G)` channel without an RP | 6 (SRC, R1-R4, RCV) | `show ip pim bsr-router`, `show ip pim rp mapping`, `show ip igmp interface`, `show ip mroute`, pings to an ASM and an SSM group |
| `16-mpls-ldp` | `mpls ip` on core links, `mpls ldp router-id Loopback0 force` (a decoy Loopback1 shows why), LIB/LFIB, penultimate-hop popping, LSP ping | 4 (PE1, P1, P2, PE2) | `show mpls ldp neighbor`, `show mpls interfaces`, `show mpls forwarding-table`, `ping mpls ipv4` |
| `17-mpls-l3vpn` (advanced) | VRF with RD and route targets, `vrf forwarding` (and re-adding the IP), iBGP VPNv4 with extended communities, eBGP PE-CE inside the VRF | 5 (CE1, PE1, P, PE2, CE2) | `show bgp vpnv4 unicast all summary`, `show ip route vrf`, `show bgp vpnv4 unicast vrf … labels`, CE-to-CE ping |

Each one has config checks, a solution summary, 3 progressive hints and 3 *Break my lab* faults. Examples: a missing
RP on the last-hop router, a static route that drags the source tree through the RP, a C-RP priority that flips the RP,
IGMPv2 silently breaking SSM, an unreachable LDP router ID, a one-sided LDP MD5 password, a wrong import route target,
or a broken LSP under healthy BGP. The checks read `show ip mroute` right after
the source ping, because `(S,G)` state ages out about 3 minutes after the source stops.
MPLS L3VPN goes beyond the ENCOR blueprint (it is ENARSI/SPCOR material), but it builds directly on VRF-lite (2.2.a).
The **Multicast and MPLS track** course (*Library & courses*) puts them in order: 14, 15, then 08-vrf-lite, 16, 17.
Standalone copies of the four labs (`mcast-*.encorlab`, `mpls-*.encorlab`, with their own ids) are attached to the
v1.6.0 release for older app versions or for sharing.

> **Not verified on real devices yet.** The recorded outputs these labs are tested against were written from Cisco
> documentation (and, for multicast, published CML `iol-xe` captures), not captured from your CML. The MPLS LSP ping
> and the `... labels` output format are the least certain parts. If a live check fails on a
> correctly solved lab, run it in *Config* grading mode and please report the device output.

### Break my lab (fault practice)
**Break my lab** rebuilds the lab in CML from its *working* configuration (starting config + reference solution) plus one
random predefined fault, such as a wrong HSRP key, a missing `ip nat outside`, an LACP member forced to `mode on`, or
a removed `next-hop-self`. You only get the trouble ticket, which describes symptoms and never the cause.

- Fix the fault and click **Check**. All lab checks, plus any extra checks for that fault, must pass. Then the panel shows what
  was broken and the exact fix.
- **Hint** gives fault-specific hints. **Reveal the answer** gives up (recorded as revealed). **End fault practice** stops it.
- **Reset** during fault practice restores the *broken* lab (same fault), so you can try again from scratch.
- The next **Break my lab** picks a different fault than the recent ones. History marks these attempts as *fault*.
- Rebuilding replaces your current device configs; the app asks first.

Your own labs can define faults too (`faults:` in lab.yaml, see [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md)). The
validator applies each fault offline and requires that a config check detects it and that the solved lab still passes.

### Printable reports
- **Lab report:** *Print report* at the bottom of a lab opens a clean page in a new tab. It shows the latest check
  (every objective with PASS/FAIL and details, mode, hints, timer), the exam result or fixed fault if any, the solution
  summary once solved, and the attempt history. *Report with command output* adds the raw `show` output (trimmed to
  4,000 characters per check).
- **Progress report:** *Print report* on the Progress page covers mastery per exam domain, weakest topics, every lab and
  the checks you fail most.
- Click **Print / Save as PDF** (or Ctrl+P) and choose *Save as PDF*. The layout is print-ready (A4/Letter, no buttons).
  From the CLI, `report <lab> -o r.html` or `report -o progress.html` writes the same pages; add `--name` to print your name.
  Lab reports are not available during an exam.

### Config snapshots
Open **Config snapshots** in a built lab and click **Save snapshot**, for example before trying something risky or to keep
a half-finished lab. The app asks CML to extract the running config of every device (HTTPS API, nodes must be BOOTED) and
saves it under `snapshots/<lab>/` in your data folder. Up to 20 snapshots are kept per lab.
- **Restore** stops and wipes the lab, sets each device's day-0 config to the saved config, and boots it again.
  Unsaved changes on the devices are lost. A snapshot taken with IOL can only be restored with IOL (same for IOSv).
- **View** shows the configs, and **.cfg** downloads them as one text file (`! device R1` sections, the `solution.cfg` format).
- **Reset** still goes back to the lab's original starting configs. Snapshots are disabled during an exam.

### Exam mode
**Exam mode** turns a lab into a timed, one-shot attempt:
1. Build the lab, then click **Exam mode**. Choose the time limit (the default depends on difficulty and size), whether
   hints are **disabled** or **cost points** (default 10 points each), and click **Start exam**.
2. During the exam the app withholds the solution, the per-check hints, the lab source and the export, and *Break my lab*
   is unavailable. A countdown is shown, and the **Hint** button (if allowed) asks before it charges you.
3. **Submit exam** grades the lab once and ends the exam. When the countdown reaches zero the lab is submitted
   automatically. A submission later than the limit plus 1 minute (for example from the CLI) scores 0%.
4. The **score report** shows the final score (raw score minus the hint penalty), hints used, time used and
   PASS/FAIL against an 80% practice target (Cisco does not publish its cut score). It is saved in the history,
   and the progress dashboard counts the exam score. *Abort exam* abandons it without recording anything.

The exam state is kept on disk (`exams/` in the data folder), so the CLI and the web UI share it and a page reload
doesn't reset the clock.

### Progress dashboard
The **Progress** page summarizes your results history and maps every lab to the
[350-401 ENCOR v1.2 exam topics](https://learningnetwork.cisco.com/s/encor-exam-topics):

- **Overall mastery**, weighted by the official domain weights (Architecture 15%, Virtualization 10%, Infrastructure 30%,
  Network Assurance 10%, Security 20%, Automation and AI 15%). Domains without labs (mostly theory) are listed but not counted.
- **Per domain and per blueprint item:** mastery, labs solved, and buttons that open the labs.
- **Weakest topics**, **checks you fail most**, a 30-day **activity** chart and your **streak** (days in a row with a Check).
- **Time spent**, estimated from the lab timer value sent with each Check.

How a score counts: the best attempt per lab, minus 5 points per hint used. It is capped at 50% if you revealed the answer
first, and exam attempts use the exam result. Labs never checked count as 0. Everything is computed locally from the
history files; nothing leaves your machine.

## Grading modes
| Mode | How | What it proves |
|---|---|---|
| **Live** | SSH to the CML console server, then read-only `show` and `ping` on each device | Real state: EIGRP neighbors up, D routes learned, loopback ping works |
| **Config** | HTTPS only: CML API `extract_configuration` on each running node, then regex checks on the running config | The configuration is right (`router eigrp 100`, network statements for 10.0.12.0 and the loopback). **It does not verify adjacencies, routes or reachability.** |
| **Auto** (default) | Tests TCP/SSH reachability of the console server first. If it's unreachable, or every live check fails to connect, it falls back to config mode | The results show which mode ran, plus a note when it fell back |

Choose the default on the Settings page (or `ENCOR_GRADING_MODE`). You can override it per Check with the mode selector, or with `check <lab> --mode live|config|auto` on the CLI.
Config extraction requires the nodes to be running. It overwrites the node's stored startup config in CML, so **Reset** re-applies the lab's original configs before rebooting.

Every check is read-only: live checks may only run `show …` and `ping …`, and config checks are regexes on the running config.

## Creating and importing labs
**Import** (the easiest way): drag `.encorlab`, `.zip` or `.yaml` files anywhere onto the Labs page, or click **Import lab**.
The file is validated immediately. You get readable errors such as `checks[2] (r1-nbr).params: missing neighbor_id`.
A valid lab appears in the list right away, marked *imported*. If a lab with that id exists, you're asked whether to replace it.
CLI: `run.bat import file.encorlab`.

Imported labs are stored apart from the built-ins, in `%APPDATA%\encorlab\labs\<id>\` (Windows) or
`~/.config/encorlab/labs/<id>/` (Linux; override with `ENCOR_USER_LABS_DIR`). Results history is kept in `history/` next to it.
**Export pack** shares a lab and **Delete lab** removes an imported one (built-ins can't be deleted).

### The `.encorlab` format

**Lab file formats** (full reference in [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md), schema in
[docs/encorlab-lab.schema.json](docs/encorlab-lab.schema.json)):
- a single `lab.yaml` with the reference solution embedded under `solution:`, or
- a `.encorlab` zip with `lab.yaml`, optional `solution.cfg`, `fixture_solved.yaml` / `fixture_blank.yaml`
  (recorded show output so live checks can be tested offline) and `README.md`.

**Lab builder** (menu *Lab builder*): a form with metadata, Markdown task, nodes (starting config + solution side by side),
links, and checks chosen from templates (OSPF/EIGRP/BGP neighbor, route present, ping, interface up, VLAN, config lines/regex…).
A YAML tab shows the same lab with live validation. *Open existing lab* edits an imported lab (built-ins open as a copy).
*Import from CML* starts from any IOL/IOSv lab in your CML. *Test lab (offline)* runs the strict validator.
*Live test in CML* (for saved labs) builds a throw-away `ENCOR-TEST-…` copy with the solution applied, grades it and deletes it.

### Lab library and courses
Click **📚 Library & courses** on the Labs page.
- **Online library:** *Load library* reads [`labs/index.json`](labs/index.json) from this repository (the only time the app
  contacts GitHub) and lists the published lab packs and courses. *Install* downloads the file over https, rejects it unless
  its **sha256 and size match the index**, validates it like any import, then installs it. You can point the library at your
  own `index.json` (https only), for example a fork or a team share.
- **Install from a URL:** paste an https link to a `.encorlab` / `.encorcourse` file and, ideally, the sha256 the author
  published. A mismatch installs nothing. Downloads are limited to 20 MB.
- **Courses** (`.encorcourse`): a zip with `course.yaml` (id, title, description, `labs:` in study order) plus optional
  `labs/<id>/` pack folders. A course may also list built-in labs. Installation is all-or-nothing: every bundled lab is
  validated first. Your courses show solved/total, a progress bar and *Continue* (the next unsolved lab). The *Course* filter
  shows a course's labs in order. *Remove* deletes the course and, if you choose, the labs it imported (never built-ins,
  never your history). Build one with `python -m encorlab course build my-course/ --labs-from examples/`.
- **Publishing:** put lab folders in `examples/` and courses in `examples/courses/<id>/course.yaml`, then run
  `python packaging/build_library.py`. It rebuilds `labs/` reproducibly (fixed zip timestamps) and regenerates
  `index.json` with the checksums. The test suite fails if `labs/` is out of date.

### AI prompt (generate labs with any AI chatbot)

**AI-generated labs.** Use any AI chat: *More > Copy prompt for any AI* (or `python -m encorlab prompt "OSPF stub lab, 4 routers"`)
copies a self-contained prompt with the rules, templates, guide, schema and an example. Import the YAML the AI returns.
The prompt template is in [docs/AI-PROMPT.md](docs/AI-PROMPT.md). An assistant that can run code should
`validate` and `pack` the lab before sending it.
The optional built-in generator (*More > Generate with AI*) calls any OpenAI-compatible API: xAI, OpenAI, Ollama or LM Studio.
Configure it in *Settings > AI generator*; there is no default provider. The API key is kept in memory, or in the OS keyring
if you tick the box, and is never written to settings.json. The generated lab is validated strictly. If it fails, the errors
are sent back to the AI for up to 2 retries, then the lab opens in the builder for review. Nothing is saved until you click Save.

Example packs live in [`examples/`](examples/) and are attached to every [release](https://github.com/Specops13/encore-lab-app/releases):
- `ospf-multiarea-stub`: OSPF multi-area, a totally stubby area and ABR /22 summarization (4 routers).
- `troubleshoot-ospf-7node`: a troubleshooting ticket on a 7-router multi-area OSPF network with one planted fault.

## Configuration
Everything can be set on the **Settings** page; `.env` / environment variables provide defaults (copy `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| CML_URL / CML_USERNAME / CML_PASSWORD | - | Controller and credentials (same as the CML web login) |
| CML_VERIFY_SSL | true | `true`, `false`, or a path to a CA bundle |
| CML_CONSOLE_HOST / CML_CONSOLE_PORT | URL host / 22 | Console server FQDN (port 22 proxy) and port, for live checks |
| ENCOR_GRADING_MODE | auto | `auto`, `live` or `config` |
| ENCOR_PLATFORM | iol | `iol` (IOL / IOL-L2, light) or `iosv` (IOSv / IOSvL2) |
| ENCOR_NODE_LIMIT | 20 | Refuse to start a lab if it would exceed this many running nodes |
| ENCOR_BOOT_TIMEOUT | 900 | Seconds to wait for nodes to boot |
| ENCOR_DEVICE_USERNAME / _PASSWORD / _ENABLE | cisco | Used only if a device console asks for a login or enable password |
| ENCOR_USER_LABS_DIR / ENCOR_DATA_DIR | settings folder | Where imported labs / results history are stored |
| ENCOR_AI_BASE_URL / ENCOR_AI_MODEL / ENCOR_AI_API_KEY | - | Optional AI generator (OpenAI-compatible) |
| ENCOR_CONSOLE_BACKEND | ssh | `ssh` (paramiko, all OSes) or `pyats` (Linux/macOS only, needs `pip install -e .[pyats]`) |

### Security and safety
- Only touches labs titled `ENCOR-…`. Deleting anything else is refused.
- Checks never change device configuration (only `show` and `ping` commands are allowed in labs).
- Imported packs are size-limited (5 MB) and path-checked. A lab file only contains data (YAML/regex), never code.
- Internet access happens only when you ask for it: *Load library* / *Install* (raw.githubusercontent.com or your URL) and
  *Check for updates* (api.github.com), or once a day if you turn on *Settings > Updates*, and *Install update*
  (the patch and `SHA256SUMS.txt` from github.com). Nothing is installed automatically.
- Patches are verified (SHA256SUMS, per-file manifest hashes, safe paths, version, runtime) before they are unpacked into
  your data folder, and are rolled back automatically if they cannot start.
- Library downloads are https-only (redirects included), size-limited and verified against the sha256 in the index before
  they are validated and installed.
- The UI listens on 127.0.0.1 only. Secrets are never returned by the API or written to logs.

## Troubleshooting and diagnostics
- **SmartScreen / antivirus warning on ENCORLab.exe:** the build is unsigned. Use *More info* > *Run anyway*, and compare the zip with `SHA256SUMS.txt`.
  The one-folder build avoids most antivirus heuristics. If yours still quarantines it, add an exclusion for the folder or run from source.
- **The console window says the port was busy:** use the address it shows, or start with `ENCORLab --port 9000`.
- **The app doesn't start (downloaded build):** the error is shown in the window and saved to `launcher-error.log` in your data folder.
- **Live checks can't connect:** see [Console access](#console-access-and-your-reverse-proxy). `doctor` tests the console server's TCP/SSH reachability. Config mode works over HTTPS only.
- **"Not built" / nodes not booting:** check the node limit, that the IOL/IOSv images exist in CML (`doctor` lists missing node definitions), and the boot timeout (`ENCOR_BOOT_TIMEOUT`).

### Common problems (running from source)
- **Install fails on Windows with "Microsoft Visual C++ 14.0 or greater is required", or with PyYAML building from source.**
  You're on a Python version that's too new (e.g. 3.15). Install Python 3.13 (64-bit) from python.org. Several versions can coexist.
  Then run `run.bat` again: the launcher picks the newest of `py -3.13`, `-3.12`, `-3.11`, `-3.10`.
- **"No supported Python (3.10-3.13) found"**: install 3.13 as above. Check what the launcher sees with `py -0p`.
- **An old .venv made with an unsupported Python**: the launchers read `.venv\pyvenv.cfg` (`.venv/pyvenv.cfg` on Linux) and recreate it automatically. You can also just delete the `.venv` folder.
- **Dependency install failed**: the launcher stops and removes the half-built `.venv` instead of starting the app. Fix the cause (network/proxy, Python version) and run it again.
- **Debian/Ubuntu "ensurepip is not available" / venv errors**: `sudo apt install python3-venv` (or `python3.11-venv` / `python3.12-venv` for your version).
- **PowerShell says scripts are disabled**: use `run.bat`, or `powershell -ExecutionPolicy Bypass -File .\run.ps1`.
- **Live checks can't connect**: see "Console access" above. `run.bat doctor` / `./run.sh doctor` tests the console server's TCP/SSH reachability. Config mode works over HTTPS only.

### Diagnostics
If the page looks wrong or buttons do nothing (especially right after an upgrade), first do a **hard refresh**:
Ctrl+Shift+R (or Ctrl+F5). Since 1.3.1, asset URLs include the version and every response is sent with `no-cache`,
so this should no longer be needed. Still stuck? Press **F12**, open the **Console** tab and look for red errors, and
check the yellow banner at the top of the page, which shows any failed request or script error. Include both when
reporting a problem, along with `run.bat doctor` output and the version shown in the header.
  The page also checks its own version against the server and asks you to reload if they don't match.

## Building the executables
PyInstaller can't cross-compile, so each OS builds its own bundle. Both use the same `packaging/encorlab.spec` and
`packaging/build.py`. The build is one-folder (an exe plus `_internal/`), not one-file: it starts faster, never unpacks to `%TEMP%`, and triggers
far fewer antivirus false positives.

- **Windows (once, on your PC):** install Python 3.12 or 3.13 from python.org, then double-click `packaging\build_exe.bat`.
  The result is `dist\ENCORLab-<version>-windows-x64.zip`. Use `set PYTHON=C:\path\python.exe` to pick a specific interpreter.
- **Linux:** `packaging/build_linux.sh` produces `dist/ENCORLab-<version>-linux-x64.tar.gz`. With `uv` installed, it uses
  python-build-standalone Python 3.12 and manylinux_2_28 wheels, so the binary runs on glibc 2.28+ even when built on a newer distro.
- **GitHub Actions:** `.github/workflows/build.yml` builds and smoke-tests both bundles (windows-latest + ubuntu-22.04) on every `v*` tag.
  The bundles are kept as workflow artifacts. To publish them, run it by hand (*Actions > build > Run workflow*), tick *publish* and enter the tag.
  Existing release assets are never overwritten. CI also builds `encorlab-patch-<version>.zip` and adds it to `SHA256SUMS.txt`.
- **App-code patch:** `python packaging/build_patch.py --out dist` writes `encorlab-patch-<version>.zip`, a deterministic
  zip with `manifest.json` (version, `min_runtime`, SHA-256 per file). The runtime is fingerprinted in
  `packaging/runtime.lock.json`: the dependencies, `encorboot.py`, `encor_launcher.py`, the spec and `build_linux.sh`.
  `--check-lock` (run by CI and the tests) fails if any of them changed. In that case bump `RUNTIME_VERSION` in
  `encorboot.py` and run `--update-lock`, so that older runtimes are told to do a full download.
- **How the bundle is laid out:** the spec keeps `encorlab` out of the frozen archive and ships it as plain files in
  `_internal/appcode/`, with a manifest. The frozen entry point (`encor_launcher.py`) runs the boot loader
  (`encorboot.py`), which picks the newest valid copy (an installed patch or the built-in one), imports it, and handles
  rollback. Most of the standard library is frozen in, so patches can use modules the current code does not import yet.
- **Smoke test:** `python packaging/smoke_test.py <exe> --version <v> --data-dir <user data dir> --pack x.encorlab` checks the CLI, the launcher, the UI assets, the lab list and imports
  (`build.py --smoke` runs it; it imports the example packs into the user data folder). With `--patch-test` it also builds test patches and checks, on the frozen build,
  install → the patched version runs and serves the UI → rollback, automatic fallback from a broken patch, and refusal of a patch that needs a newer runtime.

The UI checks versions on load and whenever the tab becomes visible again. It shows a banner if the cached `app.js` is older than
the page, or if the app was updated while the tab was open. Cache-busting (`?v=<version>` plus `no-cache`) is unchanged.

## Project layout
```
encorlab/                 the application (Python package)
  cli.py                  CLI (typer)                     launcher.py   desktop launcher (packaged builds)
  service.py              build/check/reset/destroy       grader.py     check engine (live + config modes)
  cml.py, cml_import.py   CML 2.9 API (virl2_client)      console.py    console server SSH (paramiko / pyATS)
  schema.py, templates.py lab schema + check templates    packs.py      .encorlab import/export/validation
  courses.py, library.py  .encorcourse + online library    faults.py     "Break my lab" faults (iosmerge.py: config merge)
  blueprint.py            ENCOR v1.2 exam topics           progress.py   progress dashboard
  exam.py, snapshots.py   exam mode, config snapshots      updates.py    update check + patch verify/install/rollback
  report.py               printable HTML reports (web/templates/report_*.html)
  solution.py             solution summary + hints        sim.py        offline simulator for validation/tests
  catalog.py, history.py  lab catalog, results history    config.py     settings, keyring, settings.json
  prompt.py, ai.py        AI prompt + optional generator  platforms.py  IOL/IOSv interface placeholders
  labs/<id>/              18 built-in labs (lab.yaml, solution.cfg, fixture_*.yaml)
  web/                    FastAPI app, templates/index.html, static/ (app.js, help.js, help.json, style.css)
  resources/              authoring guide + example lab (source of docs/)
docs/                     LAB-AUTHORING.md, AI-PROMPT.md, JSON Schema, example lab, images/
examples/                 example packs and courses/ (sources of labs/)
labs/                     online library: built packs, courses and index.json (packaging/build_library.py)
encorboot.py              boot loader for packaged builds: picks the app-code bundle, rollback, RUNTIME_VERSION
encor_launcher.py         frozen entry point (runs encorboot, then encorlab.launcher)
packaging/                PyInstaller spec, build.py, build_patch.py + runtime.lock.json, build_exe.bat, build_linux.sh, smoke_test.py, icon
tests/                    pytest suite (no CML needed)
.github/workflows/        CI: test + build/smoke-test Windows and Linux bundles
run.bat, run.ps1, run.sh  from-source launchers (create .venv, install, start)
```

## Development / tests
```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q        # unit + simulated end-to-end tests (no CML needed)
.venv/bin/python -m encorlab validate
```
Built-in labs live in `encorlab/labs/<id>/` (same format as packs). In configs, checks and fixtures, `%if0%` / `%if0s%`
become `Ethernet0/0` / `Et0/0` on IOL and `GigabitEthernet0/0` / `Gi0/0` on IOSv.
After changing the schema, templates, guide or example, run `python -m encorlab docs` (a test checks `docs/` is current).

## Version and changelog
Current version: **1.5.0**. It is shown in the UI header, by `ENCORLab version` and by `/api/health`.
See [CHANGELOG.md](CHANGELOG.md) for what changed in each release, and [Releases](https://github.com/Specops13/encore-lab-app/releases) for downloads.
