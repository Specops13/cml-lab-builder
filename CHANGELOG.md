# Changelog

All notable changes to ENCOR Lab Builder. Versions follow `MAJOR.MINOR.PATCH`.

## [Unreleased]
### Added
- **Break my lab (fault practice).** Each built-in lab has 3 predefined faults (33 in total). *Break my lab* rebuilds the
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
