# Changelog

All notable changes to ENCOR Lab Builder. Versions follow `MAJOR.MINOR.PATCH`.

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
