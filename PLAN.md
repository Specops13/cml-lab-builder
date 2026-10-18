# ENCOR Lab Builder & Grader for CML 2.x — Implementation Plan (Phase 1)

## 0. Verified facts (sources: developer.cisco.com/docs/modeling-labs, pypi.org/project/virl2-client)
- Client: `virl2_client` (PyPI), latest 2.10.1 (Sep 2026), Python >=3.10, deps httpx. Extra `[pyats]` adds pyATS (not Genie); full parsing needs `pip install "pyats[full]"`.
- **Client version MUST match controller minor version** (e.g. controller 2.8.x -> `virl2-client<2.9`). App pins at install time after reading `/api/v0/system_information`.
- **CML-Free (since 2.8): max 5 simultaneously running nodes.** Unmanaged switches and external connectors do NOT count. Free refplat ISO includes only **IOL (`iol-xe`), IOL-L2 (`ioll2-xe`), ASAv** + Linux hosts (Ubuntu/Alpine/Desktop). No IOSv/CSR1000v/Cat8000v on Free. Personal=20 nodes, Personal Plus=40.
- Expired paid licenses revert to Free-tier behavior (status bar "OK (FREE-TIER)").

## 1. Architecture
Python package `encorlab`, CLI via Typer:
```
encorlab doctor                 # connectivity, version, license tier/node limit, available node defs
encorlab list                   # catalog with domain, node count, required images
encorlab validate [lab]         # offline schema + semantic validation (no CML needed)
encorlab build <lab> [--start]  # import topology, start, wait for boot
encorlab task <lab>             # print task text
encorlab check <lab> [--json]   # grade via console, per-check pass/fail + hints
encorlab reset <lab>            # stop, wipe, re-import initial configs
encorlab destroy <lab>          # stop, wipe, remove
```
Modules: `config.py`, `cml.py` (thin wrapper over virl2_client, the only module touching the API), `catalog/` (YAML labs), `schema.py` (pydantic), `builder.py`, `connect.py` (console sessions), `grader.py` + `checks/` (check types), `report.py` (rich tables/JSON). Web UI (FastAPI) deferred to a later phase; it would reuse the same core.

## 2. Configuration
Env vars (optionally `.env`): `CML_URL`, `CML_USERNAME`, `CML_PASSWORD`, `CML_VERIFY_SSL` (true/false/path-to-CA; default true, warn when false), `ENCOR_LAB_PREFIX` (default `ENCOR-`), `ENCOR_NODE_LIMIT` (override autodetected limit), `ENCOR_PLATFORM` (`iol` default | `iosv` | `cat8000v`). Credentials never written to disk or logs. Device creds for console login are defined per lab (default cisco/cisco), also overridable.

## 3. Lab definition format (one YAML per lab)
```yaml
id: ospf-multiarea
title: OSPF Multi-Area
blueprint: ["3.2.a", "3.2.b"]       # ENCOR domain refs
difficulty: 2
platforms: [iol]                    # images that work
nodes:
  - {name: R1, kind: router, x: 0, y: 0, config: |  # initial (partial) config
      hostname R1 ...}
links:
  - {a: R1:Ethernet0/0, b: R2:Ethernet0/0}
task: |
  Markdown task text ...
checks:
  - id: r1-adj-area0
    device: R1
    command: show ip ospf neighbor
    type: regex|parsed|ping|config_contains
    expect: ...                      # pattern / jsonpath+value / success-rate
    points: 10
    hint: "..."
```
`kind` (router/switch/host) maps to node definitions per platform profile: iol -> `iol-xe`/`ioll2-xe`/`alpine`; iosv -> `iosv`/`iosvl2`; cat8000v -> `cat8000v`/`iosvl2`. Interface names are also mapped per platform (IOL `Ethernet0/0` vs IOSv `GigabitEthernet0/0`), so check commands use `{intf:R1:1}` placeholders. Builder renders this into native CML lab YAML (`lab:`/`nodes:`/`links:` with `node_definition`, `configuration`, interface slots) and imports via `client.import_lab(yaml, title)`. The exact YAML schema version is taken from an export off the user's controller (`lab.download()`) to avoid guessing.

## 4. Starter catalog (all ≤5 counted nodes, IOL-compatible)
| # | Lab | Blueprint (350-401 v1.1) | Nodes |
|---|-----|-----|-----|
|1|VLANs, 802.1Q trunks, Rapid-PVST root/priority|3.1.a, 3.1.c|3 L2 + 1 host... ≤5|
|2|EtherChannel LACP/PAgP L2 + L3|3.1.b|2 L2 + 2 hosts|
|3|OSPFv2 multi-area, summarization, stub, passive|3.2.b|4 routers|
|4|EIGRP named mode, variance, stub, auth|3.2.a|3 routers|
|5|BGP eBGP + iBGP, update-source, next-hop-self, local-pref|3.2.c|4 routers|
|6|HSRP v2 priority/preempt/tracking (+VRRP stretch)|3.3.a|2 L3 sw/routers + 1 L2 + 1 host|
|7|ACLs + NAT/PAT|5.1, 3.3.b|3 routers|
|8|VRF-lite with route leaking|2.2.a|3 routers|
|9 (opt)|GRE over IPsec with OSPF|2.2.b, 2.2.c|3 routers|
|10|NTP, syslog, SNMPv3, NetFlow/IP SLA|3.3.c, 4.x|3 routers|
Each lab ships broken/incomplete initial configs + task text + 5–12 checks. Each lab is verified by an included `solution.cfg` (used only by tests and `--self-test`).

## 5. Device access & grading
Primary: **CML console via pyATS** (no network path from box to devices needed, only to the controller). `lab.get_pyats_testbed()` produces a testbed using the CML terminal server (SSH to controller port 22, `open /<lab>/<node>/0`). virl2_client also offers `ClientLibrary.pyats` helpers (`lab.pyats.sync_testbed(user, pass)`, `node.run_command(cmd)`). Fallback: external connector + mgmt IPs + Netmiko SSH (optional, needs network reachability).
Check types: `regex` (raw text, always available), `parsed` (Genie parser when `pyats[full]` installed, else TextFSM/ntc-templates), `ping` (success rate ≥ X), `config_contains` (`show running-config | section ...`). Grader runs read-only show commands only; never changes device config. Output: score, per-check result, hint for failures, saved JSON history.

## 6. Robustness
- Boot wait: `lab.start(wait=True)` then poll `lab.has_converged()` + per-node `booted` state, then console probe for prompt; configurable timeout (default 15 min, IOL boots fast).
- Pre-flight: refuse to start if (counted nodes in lab + already-running counted nodes) > node limit; offer to stop other labs. Verify required node definitions exist (`client.definitions.node_definitions()`).
- Idempotency: labs tagged/titled `ENCOR-<id>`; `build` reuses existing lab (prompt or `--rebuild`). Never touches labs without the prefix.
- Cleanup: `destroy` = stop -> wipe -> remove; trap Ctrl-C during build.
- Retries with backoff on httpx errors; clear messages for auth/TLS/version-mismatch.

## 7. Testing
- Unit: pydantic schema, rendering to CML YAML (golden files), interface/platform mapping, node-limit math, check evaluators against captured show-output fixtures, all with mocked `ClientLibrary` (no network).
- `encorlab validate --all` in CI: every lab parses, links reference real interfaces, ≤ limit, checks reference existing devices.
- Integration (opt-in, `CML_URL` set): build -> apply solution.cfg -> check must score 100%; build untouched -> check must fail expected checks; destroy.

## 8. Open questions for Dylan
1. CML version (exact, e.g. 2.8.1/2.9/2.10)? Determines client pin.
2. License tier: Free (5 nodes, IOL only) / Personal (20) / Personal Plus / Enterprise?
3. Which images are installed (IOL/IOL-L2? IOSv/IOSvL2? CSR1000v/Cat8000v)?
4. Can this box reach the CML URL (public IP/VPN/tunnel)? If not, the app runs on your PC and I test with mocks only.
5. Self-signed cert (disable verify or provide CA)?
6. Preferred device credentials / any labs or topics to add or drop (e.g. wireless, SD-Access are not labbable in CML)?
7. CLI only OK for v1, web UI later?

## 9. Phase 2 decisions (Oct 16 2026)
- Dylan: CML 2.9.1 Personal (20 nodes), all refplats; default IOL, IOSv as an option; Windows 11 + Debian; Tailscale with a Let's Encrypt reverse proxy (TLS verification on).
- virl2_client pinned to `>=2.9.0,<2.10`.
- pyATS has no native Windows support (Cisco docs: use WSL), so the default console backend is paramiko SSH to the CML console server. pyATS is an optional backend.
- Topology YAML schema 0.2.2 (the same shape as Cisco's cml-community labs). IOL interfaces are Ethernet0/0-0/3 on slots 0-3.
- (Phase 2) Scope was narrowed to eigrp-basic. The staged labs were enabled in phase 3 (see section 10).
- Two grading modes. Live = console over SSH, via a separate Console server FQDN/port (a proxy must be TCP passthrough). Config = HTTPS only: Node.extract_configuration() then Node.configuration (virl2_client 2.9.1); the node must be BOOTED. Auto = probe the console, fall back to config with a visible note. Each check is tagged mode: live|config. Reset re-applies the original configs, because extraction overwrites the stored day-0 config.
- (Phase 2) staged labs lacked config checks. Added in phase 3.

## 10. Phase 3 (v1.2.0): user labs, builder, AI
- The 10 staged labs are enabled. Each has live and config checks, and all of them pass offline (solution 100%, starting config 0%, both platforms).
- User labs go in `<settings folder>/labs/<id>/`, separate from the built-ins. Ids clashing with a built-in are rejected.
- Pack = zip (`.encorlab`) with lab.yaml (+ solution.cfg, fixtures, README), or a single YAML with an embedded `solution:`. Limits: 5 MB, safe paths.
- Strict lint (pack/import/AI): a solution is required, config checks must score 100% with the solution and 0% on the starting config, and live checks must do the same when fixtures exist.
- Builder edits reuse the source lab's fixtures while they still match. Otherwise the fixtures are dropped with a warning.
- The AI generator is optional and OpenAI-compatible, with no default provider. Its key is kept in memory or the keyring only. It retries up to 2 times, feeding the lint errors back.
- docs/ is generated by `encorlab docs`. A test keeps it in sync.
