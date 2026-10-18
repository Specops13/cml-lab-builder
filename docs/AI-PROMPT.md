# AI prompt for generating ENCOR Lab Builder labs

How to use it:

- **Any AI chat (recommended):** copy everything below the line, replace the
  `{{DESCRIBE YOUR LAB HERE ...}}` placeholder with the lab you want, and paste it into the chat.
  The app's *More > Copy prompt for any AI* menu and `python -m encorlab prompt "your request"` do the
  same with the request already filled in.
- **Assistants that can run code:** write the YAML to `lab.yaml` (or a folder with `lab.yaml`,
  `solution.cfg`, `fixture_solved.yaml` and `fixture_blank.yaml`), then run
  `python -m encorlab validate <path>` until it prints `OK` (solution 100%, starting config 0%), and
  `python -m encorlab pack <path> -o <id>.encorlab`. Send the `.encorlab` file (or the `.yaml`).
- **Importing:** drag the file onto the app's Labs page, click *Import lab*, or run
  `python -m encorlab import <file>`.

Generated from the app (`python -m encorlab docs`). Do not edit by hand.

---

You are generating a Cisco CCNP ENCOR (350-401) practice lab for the 'ENCOR Lab Builder' app,
which builds the lab in Cisco Modeling Labs 2.9 and grades it automatically.

## Lab request
{{DESCRIBE YOUR LAB HERE: topic, devices, difficulty, blueprint items}}

## OUTPUT RULES
- Output exactly ONE lab as YAML that follows the JSON Schema and the guide. Put it in a single ```yaml code block
  and write nothing after the block. (When asked for JSON, output the same structure as one JSON object.)
- Include `solution:` with the exact config lines that solve the lab, for every device that needs changes.
- Include `solution_summary:` (Markdown, REQUIRED): root cause / what was missing, the exact fix commands per device
  in code blocks (with %ifN% placeholders), and 1-3 sentences on why it works.
- Include `hints:`, an ordered list of 2-4 progressive hints (vaguest first). Never paste the full solution into a hint.
- Starting configs (`nodes[].config`) contain only what the student is given (addressing, no shutdown). Never the answer.
- Use %if0%..%if3% / %if0s%..%if3s% for data interfaces everywhere. Never write Ethernet0/x or GigabitEthernet0/x.
- Provide BOTH live checks and config checks. For each key objective, use a live check (state: adjacency/route/ping)
  AND a config check (the command that creates it). Prefer the templates.
- Every config check must pass when `solution` is applied to the starting config, and fail on the starting config alone.
  Match running-config lines exactly as IOS prints them (see "Writing regexes").
- Keep to 2-6 nodes; use only kind router/switch; platforms [iol, iosv] unless a feature needs one.
- id: lowercase-with-dashes, unique and descriptive.

## Check templates (machine-readable)
```json
[
 {
  "name": "ospf_neighbor",
  "mode": "live",
  "title": "OSPF neighbor FULL",
  "params": [
   {
    "name": "neighbor_id",
    "description": "Neighbor router ID",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "eigrp_neighbor",
  "mode": "live",
  "title": "EIGRP neighbor up",
  "params": [
   {
    "name": "address",
    "description": "Neighbor IP address",
    "required": true,
    "default": null
   },
   {
    "name": "interface",
    "description": "Local interface (%if0% or Ethernet0/0)",
    "required": false,
    "default": null
   }
  ]
 },
 {
  "name": "bgp_established",
  "mode": "live",
  "title": "BGP session Established",
  "params": [
   {
    "name": "neighbor",
    "description": "Neighbor IP",
    "required": true,
    "default": null
   },
   {
    "name": "remote_as",
    "description": "Neighbor AS number",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "route_present",
  "mode": "live",
  "title": "Route present in routing table",
  "params": [
   {
    "name": "prefix",
    "description": "Prefix, e.g. 2.2.2.2/32",
    "required": true,
    "default": null
   },
   {
    "name": "code",
    "description": "Route code: O, O IA, O E2, D, D EX, B, S, C",
    "required": true,
    "default": null
   },
   {
    "name": "via",
    "description": "Next hop",
    "required": false,
    "default": null
   },
   {
    "name": "vrf",
    "description": "VRF name",
    "required": false,
    "default": null
   }
  ]
 },
 {
  "name": "ping",
  "mode": "live",
  "title": "Ping succeeds",
  "params": [
   {
    "name": "target",
    "description": "Destination IP",
    "required": true,
    "default": null
   },
   {
    "name": "source",
    "description": "Source interface or IP",
    "required": false,
    "default": null
   },
   {
    "name": "min_success",
    "description": "Minimum success %",
    "required": false,
    "default": 80
   }
  ]
 },
 {
  "name": "interface_up",
  "mode": "live",
  "title": "Interface up/up",
  "params": [
   {
    "name": "interface",
    "description": "Interface (%if0% or Ethernet0/0, Loopback0, Tunnel0)",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "vlan_exists",
  "mode": "live",
  "title": "VLAN exists and is active",
  "params": [
   {
    "name": "vlan",
    "description": "VLAN ID",
    "required": true,
    "default": null
   },
   {
    "name": "name",
    "description": "VLAN name",
    "required": false,
    "default": null
   }
  ]
 },
 {
  "name": "show_contains",
  "mode": "live",
  "title": "Show command output matches regex",
  "params": [
   {
    "name": "command",
    "description": "show command",
    "required": true,
    "default": null
   },
   {
    "name": "pattern",
    "description": "Python regex (multiline)",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "config_lines",
  "mode": "config",
  "title": "Running config contains lines",
  "params": [
   {
    "name": "lines",
    "description": "One or more exact config lines (newline separated)",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "config_regex",
  "mode": "config",
  "title": "Running config matches regex",
  "params": [
   {
    "name": "pattern",
    "description": "Python regex (multiline)",
    "required": true,
    "default": null
   }
  ]
 },
 {
  "name": "config_router",
  "mode": "config",
  "title": "Routing process configured",
  "params": [
   {
    "name": "protocol",
    "description": "ospf, eigrp or bgp",
    "required": true,
    "default": null
   },
   {
    "name": "process",
    "description": "Process ID / AS number",
    "required": true,
    "default": null
   }
  ]
 }
]
```

## Authoring guide
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
| blueprint | yes | ENCOR 350-401 v1.1 items, e.g. `["3.2.b"]` |
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

## Full example
See the example below (also shipped as `example-lab.yaml`).


## Example lab (valid; copy its structure)
```yaml
# yaml-language-server: $schema=./encorlab-lab.schema.json
id: example-eigrp-pair
title: "Example: EIGRP between two routers"
blueprint: ["3.2.a"]
domain: "3.0 Infrastructure - Layer 3"
difficulty: 1
platforms: [iol, iosv]
summary: Two routers, one link. Enable EIGRP AS 100 and exchange loopbacks.
author: ENCOR Lab Builder
version: "1"
nodes:
  - name: R1
    kind: router
    x: -150
    y: 0
    config: |
      interface Loopback0
       ip address 1.1.1.1 255.255.255.255
      interface %if0%
       description to R2
       ip address 10.0.12.1 255.255.255.0
       no shutdown
  - name: R2
    kind: router
    x: 150
    y: 0
    config: |
      interface Loopback0
       ip address 2.2.2.2 255.255.255.255
      interface %if0%
       description to R1
       ip address 10.0.12.2 255.255.255.0
       no shutdown
links:
  - {a: {node: R1, port: 0}, b: {node: R2, port: 0}}
task: |
  # EIGRP between two routers

  R1 %if0% (10.0.12.1/24) connects to R2 %if0% (10.0.12.2/24).
  Loopback0: R1 1.1.1.1/32, R2 2.2.2.2/32.

  1. Enable EIGRP AS 100 on both routers.
  2. Advertise the link and each Loopback0.
  3. R1 must ping 2.2.2.2 sourced from Loopback0.
checks:
  # live checks: run over the device console
  - id: r1-nbr
    template: eigrp_neighbor
    device: R1
    params: {address: 10.0.12.2, interface: "%if0%"}
    hint: Same AS on both routers and a network statement for 10.0.12.0/24.
  - id: r1-route
    template: route_present
    device: R1
    params: {prefix: 2.2.2.2/32, code: D, via: 10.0.12.2}
    hint: R2 must advertise its Loopback0.
  - id: r1-ping
    template: ping
    device: R1
    params: {target: 2.2.2.2, source: Loopback0}
  # config checks: regex on the running config fetched through the CML API
  - id: r1-cfg-eigrp
    template: config_router
    device: R1
    params: {protocol: eigrp, process: 100}
  - id: r1-cfg-nets
    mode: config
    description: R1 advertises 10.0.12.0/24 and 1.1.1.1/32
    device: R1
    match:
      - '^\s+network 10\.(0\.0\.0|0\.12\.\d+)( [0-9.]+)?\s*$'
      - '^\s+network 1\.(0\.0\.0|1\.1\.1)( [0-9.]+)?\s*$'
    hint: network 10.0.12.0 0.0.0.255 and network 1.1.1.1 0.0.0.0
  - id: r2-cfg-eigrp
    template: config_router
    device: R2
    params: {protocol: eigrp, process: 100}
solution:
  R1: |
    router eigrp 100
     network 1.1.1.1 0.0.0.0
     network 10.0.12.0 0.0.0.255
  R2: |
    router eigrp 100
     network 2.2.2.2 0.0.0.0
     network 10.0.12.0 0.0.0.255
solution_summary: |
  **What was missing:** EIGRP was not enabled on either router.

  **Fix:** on both routers, enable EIGRP AS 100 on the link and on the loopback.

  R1:
  ```
  router eigrp 100
   network 1.1.1.1 0.0.0.0
   network 10.0.12.0 0.0.0.255
  ```
  R2:
  ```
  router eigrp 100
   network 2.2.2.2 0.0.0.0
   network 10.0.12.0 0.0.0.255
  ```

  **Why it works:** the `network` statements enable EIGRP on the matching interfaces. Both routers use
  AS 100 with default K-values, so they form a neighborship and exchange their loopbacks as `D` routes.
hints:
  - The task asks for EIGRP. Which AS number must both routers use?
  - Each router must run EIGRP on the shared link and on its own loopback.
  - "Under `router eigrp 100`: `network 10.0.12.0 0.0.0.255` plus `network <your loopback> 0.0.0.0`."
```

## JSON Schema
```json
{
 "$defs": {
  "Check": {
   "additionalProperties": false,
   "description": "A grading check. Either give command/match/absent/min_success directly, or a\n`template` + `params` (see LAB-AUTHORING.md).",
   "properties": {
    "id": {
     "title": "Id",
     "type": "string"
    },
    "description": {
     "default": "",
     "title": "Description",
     "type": "string"
    },
    "device": {
     "title": "Device",
     "type": "string"
    },
    "mode": {
     "default": "live",
     "description": "live = show/ping over the device console; config = regex on the running config fetched via the CML API",
     "enum": [
      "live",
      "config"
     ],
     "title": "Mode",
     "type": "string"
    },
    "command": {
     "default": "",
     "description": "live only: read-only 'show ...' or 'ping ...' command",
     "title": "Command",
     "type": "string"
    },
    "match": {
     "default": [],
     "description": "Python regexes (multiline: ^ and $ match per line) that must ALL match",
     "items": {
      "type": "string"
     },
     "title": "Match",
     "type": "array"
    },
    "absent": {
     "default": [],
     "description": "Python regexes that must NOT match",
     "items": {
      "type": "string"
     },
     "title": "Absent",
     "type": "array"
    },
    "min_success": {
     "anyOf": [
      {
       "maximum": 100,
       "minimum": 1,
       "type": "integer"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "live ping checks: minimum 'Success rate is N percent'",
     "title": "Min Success"
    },
    "points": {
     "default": 1,
     "minimum": 1,
     "title": "Points",
     "type": "integer"
    },
    "hint": {
     "default": "",
     "description": "Shown to the student when the check fails",
     "title": "Hint",
     "type": "string"
    },
    "template": {
     "anyOf": [
      {
       "type": "string"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "Optional check template (see LAB-AUTHORING.md)",
     "title": "Template"
    },
    "params": {
     "anyOf": [
      {
       "additionalProperties": true,
       "type": "object"
      },
      {
       "type": "null"
      }
     ],
     "default": null,
     "description": "Parameters for the template",
     "title": "Params"
    }
   },
   "required": [
    "id",
    "device"
   ],
   "title": "Check",
   "type": "object"
  },
  "Endpoint": {
   "additionalProperties": false,
   "properties": {
    "node": {
     "description": "Node name",
     "title": "Node",
     "type": "string"
    },
    "port": {
     "description": "Data port index 0-3 (= %if0%..%if3%)",
     "exclusiveMaximum": 4,
     "minimum": 0,
     "title": "Port",
     "type": "integer"
    }
   },
   "required": [
    "node",
    "port"
   ],
   "title": "Endpoint",
   "type": "object"
  },
  "Fault": {
   "additionalProperties": false,
   "description": "A predefined fault for \"Break my lab\": applied on top of a working (solved) lab so the student\ngets a realistic trouble ticket. `config` is IOS config applied after the solution (use `no ...`\nto remove lines). Optional `checks` are graded in addition to the lab checks while the fault is active.",
   "properties": {
    "id": {
     "description": "Short unique id, e.g. 'r2-wrong-key'",
     "title": "Id",
     "type": "string"
    },
    "title": {
     "description": "Short name of the fault (shown after it is fixed)",
     "title": "Title",
     "type": "string"
    },
    "ticket": {
     "description": "Symptom-only trouble ticket shown to the student (never the cause)",
     "title": "Ticket",
     "type": "string"
    },
    "device": {
     "description": "Device the fault is applied to",
     "title": "Device",
     "type": "string"
    },
    "config": {
     "description": "IOS config applied after the solution, e.g. 'interface %if0%\\n shutdown'",
     "title": "Config",
     "type": "string"
    },
    "explanation": {
     "description": "Markdown: root cause and the exact fix, shown after the fault is fixed or revealed",
     "title": "Explanation",
     "type": "string"
    },
    "hints": {
     "default": [],
     "description": "Progressive hints for this fault, vaguest first",
     "items": {
      "type": "string"
     },
     "title": "Hints",
     "type": "array"
    },
    "checks": {
     "default": [],
     "description": "Extra checks graded while this fault is active",
     "items": {
      "$ref": "#/$defs/Check"
     },
     "title": "Checks",
     "type": "array"
    }
   },
   "required": [
    "id",
    "title",
    "ticket",
    "device",
    "config",
    "explanation"
   ],
   "title": "Fault",
   "type": "object"
  },
  "Link": {
   "additionalProperties": false,
   "properties": {
    "a": {
     "$ref": "#/$defs/Endpoint"
    },
    "b": {
     "$ref": "#/$defs/Endpoint"
    }
   },
   "required": [
    "a",
    "b"
   ],
   "title": "Link",
   "type": "object"
  },
  "Node": {
   "additionalProperties": false,
   "description": "A router or switch. `config` is the starting config (hostname is added automatically).",
   "properties": {
    "name": {
     "description": "Node label/hostname: letter first, then letters/digits/_/-, max 31 chars (e.g. R1, SW1)",
     "title": "Name",
     "type": "string"
    },
    "kind": {
     "description": "router -> iol-xe / iosv; switch -> ioll2-xe / iosvl2",
     "enum": [
      "router",
      "switch"
     ],
     "title": "Kind",
     "type": "string"
    },
    "x": {
     "default": 0,
     "description": "Canvas X position in CML",
     "title": "X",
     "type": "integer"
    },
    "y": {
     "default": 0,
     "description": "Canvas Y position in CML",
     "title": "Y",
     "type": "integer"
    },
    "config": {
     "description": "Starting IOS config (no hostname line needed). Use %if0%..%if3% for data interfaces",
     "title": "Config",
     "type": "string"
    }
   },
   "required": [
    "name",
    "kind",
    "config"
   ],
   "title": "Node",
   "type": "object"
  }
 },
 "additionalProperties": false,
 "description": "One ENCOR practice lab.",
 "properties": {
  "id": {
   "description": "Lowercase id: letters, digits, dashes (2-41 chars). Also the folder name",
   "title": "Id",
   "type": "string"
  },
  "title": {
   "title": "Title",
   "type": "string"
  },
  "blueprint": {
   "description": "ENCOR 350-401 v1.1 blueprint items, e.g. ['3.2.b']",
   "items": {
    "type": "string"
   },
   "title": "Blueprint",
   "type": "array"
  },
  "domain": {
   "description": "Blueprint domain, e.g. '3.0 Infrastructure - Layer 3'",
   "title": "Domain",
   "type": "string"
  },
  "difficulty": {
   "description": "1 (easy) to 5 (hard)",
   "maximum": 5,
   "minimum": 1,
   "title": "Difficulty",
   "type": "integer"
  },
  "platforms": {
   "default": [
    "iol",
    "iosv"
   ],
   "description": "Image profiles the lab supports",
   "items": {
    "enum": [
     "iol",
     "iosv"
    ],
    "type": "string"
   },
   "title": "Platforms",
   "type": "array"
  },
  "summary": {
   "description": "One-line summary for the catalog",
   "title": "Summary",
   "type": "string"
  },
  "nodes": {
   "items": {
    "$ref": "#/$defs/Node"
   },
   "title": "Nodes",
   "type": "array"
  },
  "links": {
   "items": {
    "$ref": "#/$defs/Link"
   },
   "title": "Links",
   "type": "array"
  },
  "task": {
   "description": "Markdown task text shown to the student",
   "title": "Task",
   "type": "string"
  },
  "checks": {
   "description": "Needs at least one live and one config check",
   "items": {
    "$ref": "#/$defs/Check"
   },
   "title": "Checks",
   "type": "array"
  },
  "solution": {
   "anyOf": [
    {
     "additionalProperties": {
      "type": "string"
     },
     "type": "object"
    },
    {
     "type": "null"
    }
   ],
   "default": null,
   "description": "Optional reference solution: device -> config lines",
   "title": "Solution"
  },
  "solution_summary": {
   "default": "",
   "description": "Markdown shown after the lab is solved (or on 'Reveal solution'): the root cause / what was missing, the exact fix commands per device, and briefly why it works. Required for new labs; if empty the app generates a fallback from `solution`",
   "title": "Solution Summary",
   "type": "string"
  },
  "hints": {
   "default": [],
   "description": "Ordered progressive hints (vague first, most specific last), revealed one at a time with the Hint button. Never paste the full answer into a hint. If empty, the per-check hints are used in check order",
   "items": {
    "type": "string"
   },
   "title": "Hints",
   "type": "array"
  },
  "faults": {
   "default": [],
   "description": "Optional predefined faults for 'Break my lab' (random troubleshooting practice on the solved lab)",
   "items": {
    "$ref": "#/$defs/Fault"
   },
   "title": "Faults",
   "type": "array"
  },
  "author": {
   "default": "",
   "title": "Author",
   "type": "string"
  },
  "version": {
   "default": "1",
   "title": "Version",
   "type": "string"
  }
 },
 "required": [
  "id",
  "title",
  "blueprint",
  "domain",
  "difficulty",
  "summary",
  "nodes",
  "links",
  "task",
  "checks"
 ],
 "title": "ENCOR Lab Builder lab definition",
 "type": "object",
 "$schema": "https://json-schema.org/draft/2020-12/schema",
 "$id": "encorlab-lab.schema.json"
}
```

Now produce the lab for the request above. Reply with one ```yaml block only.