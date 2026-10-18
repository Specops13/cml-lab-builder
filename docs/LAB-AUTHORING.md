# ENCOR Lab Builder - Lab Authoring Guide

A lab is one YAML document (`lab.yaml`). You can share it as:
- **a single `.yaml` file** with the reference solution embedded under `solution:` (simplest), or
- **a `.encorlab` pack**: a zip containing `lab.yaml`, plus optional `solution.cfg`, `fixture_solved.yaml`,
  `fixture_blank.yaml` and `README.md`, all at the zip root.

To import: drag the file onto the catalog page, click **Import lab**, or run `encorlab import <file>`.
To check a lab before sending it: `encorlab validate <file-or-folder>`. To build a pack: `encorlab pack <folder-or-yaml> -o name.encorlab`.
The JSON Schema is `encorlab-lab.schema.json` (`encorlab schema`). For autocomplete in VS Code (YAML extension), add
`# yaml-language-server: $schema=./encorlab-lab.schema.json` as the first line.

## Hard rules (the validator enforces them)
1. `id`: lowercase letters, digits and dashes, 2-41 characters (e.g. `ospf-multiarea-stub`). It must not reuse a built-in lab id.
2. Nodes: `kind` is `router` or `switch`. Names start with a letter (`R1`, `SW1`, `ABR`). Keep labs small: 2-6 nodes, max 20.
3. **Interfaces**: each node has 4 data ports, numbered 0-3. Never write literal interface names. Use placeholders:
   - `%if0%` .. `%if3%` -> long name (`Ethernet0/0` on IOL, `GigabitEthernet0/0` on IOSv)
   - `%if0s%` .. `%if3s%` -> short name (`Et0/0` / `Gi0/0`) as shown in table outputs (`show ip ospf interface brief`, `show etherchannel summary`, `show interfaces trunk`, `show standby brief`, `show ip eigrp neighbors`)

   Placeholders work in node configs, solutions, task text, check commands and regexes.
   Loopbacks, Tunnels, Vlan SVIs and Port-channels are written literally (`Loopback0`, `Tunnel0`, `Vlan10`, `Port-channel1`).
4. Links connect `{node, port}` pairs. Each port is used at most once, and a node can't link to itself.
5. `checks` must contain **both** live checks (`mode: live`, the default) **and** config checks (`mode: config`).
6. Include a **reference solution** (`solution:` map, device -> config lines to add). The validator applies it to the starting
   configs and requires every config check to pass (100%). On the untouched starting config, the checks must fail (0% when packing).
7. Starting configs only contain what the student is given (usually IP addressing and `no shutdown`). Never put the answer there.
   The app adds `hostname`, `no ip domain lookup`, `no logging console` and console line settings automatically.
8. Live commands must be read-only: they start with `show ` or `ping `.
9. Write a **`solution_summary`** (required for new labs; the validator warns when it's missing) and an ordered **`hints`** list.

## Top-level fields
| Field | Required | Notes |
|---|---|---|
| id, title | yes | |
| blueprint | yes | ENCOR 350-401 v1.2 items, e.g. `["3.2.b"]` |
| domain | yes | e.g. `"3.0 Infrastructure - Layer 3"` |
| difficulty | yes | 1-5 |
| platforms | no | default `[iol, iosv]`. Use both unless a feature needs one image |
| summary | yes | one line for the catalog |
| nodes, links | yes | see above |
| task | yes | Markdown. Give the student addressing, goals and verification commands |
| checks | yes | see below |
| solution | recommended | `{R1: "router ospf 1\n network ...\n"}`. Required for `pack` and AI generation |
| solution_summary | yes (new labs) | Markdown shown when the student scores 100% (or clicks *Reveal solution*). See below |
| hints | recommended | Ordered list, vaguest first. The *Hint* button reveals them one at a time ("Hint 2 of 3") |
| faults | optional | Predefined faults for *Break my lab* (see below) |
| author, version | no | free text |

## Solution summary and hints
`solution_summary` is a short Markdown block with three parts:
1. **Root cause** (troubleshooting labs) or **what was missing** (config labs): one or two sentences.
2. **Fix**: the exact commands, per device, in fenced code blocks. Use the `%ifN%` placeholders.
3. **Why it works**: one to three sentences.

````yaml
solution_summary: |
  **What was missing:** EIGRP was not enabled on either router.

  **Fix**
  R1:
  ```
  router eigrp 100
   network 1.1.1.1 0.0.0.0
   network 10.0.12.0 0.0.0.255
  ```

  **Why it works:** the `network` statements enable EIGRP on the matching interfaces.
  Both routers use AS 100, so they form a neighborship and exchange their loopbacks.
hints:
  - Which routing protocol and AS number does the task ask for?
  - Both routers need the protocol enabled on the link and on their loopback.
  - "Use `network 10.0.12.0 0.0.0.255` and `network <loopback> 0.0.0.0` under `router eigrp 100`."
````

If `solution_summary` is empty, the app generates a fallback that lists the solution lines per device.
If `hints` is empty, the Hint button uses the per-check `hint` texts in check order.
Hints go from vague to specific. The last one may name the feature, but should not paste the whole solution.

## Faults ("Break my lab")

Optional. Each fault breaks the **solved** lab in one realistic way. *Break my lab* rebuilds the lab with
starting config + solution + one random fault config, and the student gets only the `ticket` (symptoms).

```yaml
faults:
  - id: r2-wrong-key            # lowercase, unique
    title: Wrong EIGRP key-string on R2
    device: R2
    ticket: R2 has had no EIGRP neighbors since a password change.   # symptoms only, never the cause
    config: |                   # IOS lines applied after the solution; use "no ..." to remove lines
      key chain EIGRP-KEYS
       key 1
        key-string WRONG
    explanation: |              # Markdown: root cause, exact fix, why
      **Root cause:** ... **Fix (R2):** ...
    hints: ["vaguest hint", "more specific hint"]
    checks:                     # optional extra checks graded while this fault is active
      - id: f-r2-cfg-key
        mode: config
        device: R2
        description: R2 uses the shared key string
        match: ['^key chain EIGRP-KEYS\s*\n\s+key 1\s*\n\s+key-string ENCOR\s*$']
```

The validator applies every fault offline (IOS-style merge: a line replaces the same setting, `no X` removes it) and
requires that at least one config-mode check (lab checks + the fault's `checks`) **fails** with the fault and that
all of them still pass without it. Avoid faults whose fix is not visible in the running config as you wrote it
(for example NTP keys, which IOS stores encrypted).

## Checks
Each check has `id`, `device`, `description` (optional when using a template), `points` (default 1) and `hint` (shown next to a failed check).
Direct form:
```yaml
- id: r1-ospf-nbr
  mode: live                      # default
  description: R1 has a FULL adjacency with 2.2.2.2
  device: R1
  command: show ip ospf neighbor
  match: ['^2\.2\.2\.2\s+\d+\s+FULL/']   # Python regex, multiline (^/$ per line); ALL must match
  absent: []                      # regexes that must NOT match
  hint: Check areas and network types.
- id: r1-ping
  device: R1
  command: ping 2.2.2.2 source Loopback0 repeat 5
  min_success: 80                 # ping checks: parse "Success rate is N percent"
  description: R1 reaches 2.2.2.2
- id: r1-cfg-area
  mode: config                    # regex on the running config (no command)
  description: Area 1 is totally stubby on the ABR
  device: R1
  match: ['^ area 1 stub no-summary\s*$']
```

### Templates (preferred: their regexes are tested against real IOS output)
Write `template:` and `params:` instead of command/match. The description is generated if you leave it out.

| template | mode | params | expands to |
|---|---|---|---|
| ospf_neighbor | live | neighbor_id | `show ip ospf neighbor` contains `<id> ... FULL/` |
| eigrp_neighbor | live | address, interface? | `show ip eigrp neighbors` row for the address (and interface) |
| bgp_established | live | neighbor, remote_as | `show ip bgp summary` row ending in a prefix count (= Established) |
| route_present | live | prefix (a.b.c.d/len), code (O, O IA, O E2, D, D EX, B, S, C), via?, vrf? | `show ip route [vrf X]` line `<code> <prefix>`. The mask is optional because IOS hides it when a major network has one mask |
| ping | live | target, source?, min_success (default 80) | `ping <target> [source X] repeat 5` |
| interface_up | live | interface | `show interfaces X` contains `X is up, line protocol is up` |
| vlan_exists | live | vlan, name? | `show vlan brief` row `<vlan> <name> active` |
| show_contains | live | command, pattern | any show command + regex |
| config_router | config | protocol (ospf/eigrp/bgp), process | `router ospf 1` / `router eigrp 100` (or named-mode AS 100) / `router bgp 65000` |
| config_lines | config | lines (newline separated) | each exact line must exist (leading spaces ignored) |
| config_regex | config | pattern | regex on the running config |

## Writing regexes that match real IOS output
- **Route tables**: when a classful network has a single mask, IOS prints `      2.0.0.0/32 is subnetted, 1 subnets` and then
  `D        2.2.2.2 [90/409600] via ...` **without** the mask. Use `route_present` or make the mask optional: `2\.2\.2\.2(/32)?\s`.
- **Codes**: `O`, `O IA`, `O E1`, `O E2`, `O N1`, `O N2`, `D`, `D EX`, `B`, `S`, `S*`, `C`, `L`. A default route learned in a
  (totally) stubby area shows as `O*IA  0.0.0.0/0`. Match with `'^O\*IA\s+0\.0\.0\.0/0'`.
- **OSPF neighbor** rows: `2.2.2.2           0   FULL/  -        00:00:35    10.0.12.2       Ethernet0/0`
  (point-to-point = `FULL/  -`; broadcast = `FULL/DR`, `FULL/BDR`, `FULL/DROTHER`).
- **Running config** (config mode): sub-commands are indented by one space (`router ospf 1` then ` network ...`).
  Under named EIGRP and BGP address families the indent is deeper, so prefer `^\s+...`.
  IOS normalizes what you type:
  - `network 10.0.12.0` without a wildcard becomes classful `network 10.0.0.0` under EIGRP
  - BGP `network` / `neighbor ... next-hop-self` lines appear under ` address-family ipv4`
  - secrets are encrypted (`key-string 7 ...`, `ntp authentication-key 1 md5 <hash> 7`), so don't match clear-text keys
  - SNMPv3 users never appear in the running config
  - VLANs appear in the running config only in VTP transparent/off mode, so check VLANs with live `show vlan brief`
- To check a line inside one interface block, use:
  `'^interface %if0%\s*\n(?:[ \t].*\n)*?[ \t]+ip ospf network point-to-point'`
- Escape dots in IP addresses (`10\.0\.12\.1`). In YAML, put regexes in single quotes.

## Offline testing
`encorlab validate <file>` checks the schema, interface names, node limit and both platforms. It then applies the solution and
grades the **config** checks (solution must be 100%, starting config 0%). Live checks are only fully tested when the pack
contains `fixture_solved.yaml` / `fixture_blank.yaml` (recorded command output: `{DEVICE: {"show ...": "output"}}`).
Otherwise only their syntax is checked, so prefer templates for live checks.
In the app, **Test lab -> Live test** builds a throw-away copy in CML with the solution applied and grades it for real.

## Pack file formats
`solution.cfg` (instead of an embedded `solution:`): one block per device, each starting with `! device NAME`:
```
! device R1
router ospf 1
 network 10.0.12.0 0.0.0.255 area 0
! device R2
router ospf 1
 network 10.0.12.0 0.0.0.255 area 0
```
`fixture_solved.yaml` / `fixture_blank.yaml`: recorded output of every live check's command, keyed by device and the
**exact expanded command** (templates expand to e.g. `show ip ospf neighbor`, `show ip route`,
`ping 1.1.1.1 source Loopback0 repeat 5`). Placeholders such as `%if0%` work in the output. Missing pings count as failed,
and other missing commands return empty output. `show running-config` is simulated from starting config + solution, so don't record it.
```yaml
R1:
  show ip ospf neighbor: |
    Neighbor ID     Pri   State           Dead Time   Address         Interface
    2.2.2.2           1   FULL/BDR        00:00:35    10.0.12.2       %if0%
```
With both fixtures present, `validate` must show `live solution=100% blank=0%` as well as config.

## Courses (`.encorcourse`)
A course is a zip that bundles labs into a study track:
```
course.yaml              # required
labs/<lab-id>/lab.yaml   # optional bundled labs, one folder per lab (+ solution.cfg, fixtures, README.md)
```
```yaml
id: ospf-mastery                 # lowercase letters, digits and dashes
title: "OSPF Mastery: design, areas and troubleshooting"
description: Three labs in study order ...
author: Your Name                # optional
version: "1.0"                   # optional
labs: [03-ospf-multiarea, ospf-multiarea-stub, troubleshoot-ospf-7node]   # study order (max 50)
```
Every listed lab must be bundled, built in, or already installed. Each bundle folder must be named after its lab id, and
every bundled lab must pass the normal validation, otherwise nothing is installed. Build and validate one with
`python -m encorlab course build <folder> [--labs-from examples/] -o my.encorcourse`.

## Full example
See the example below (also shipped as `example-lab.yaml`).
