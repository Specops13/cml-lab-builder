"""Builds the self-contained prompt used by 'Copy prompt for any AI', the built-in
AI generator and docs/AI-PROMPT.md."""
from __future__ import annotations

import json
from pathlib import Path

from .schema import Lab
from .templates import catalog as template_catalog

RES = Path(__file__).parent / "resources"
PLACEHOLDER = "{{DESCRIBE YOUR LAB HERE: topic, devices, difficulty, blueprint items}}"


def json_schema() -> dict:
    s = Lab.model_json_schema()
    s["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    s["$id"] = "encorlab-lab.schema.json"
    s["title"] = "CML Lab Builder lab definition"
    return s


def guide() -> str:
    return (RES / "LAB-AUTHORING.md").read_text(encoding="utf-8")


def example() -> str:
    return (RES / "example-lab.yaml").read_text(encoding="utf-8")


RULES = """\
OUTPUT RULES
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
- id: lowercase-with-dashes, unique and descriptive (never the id of a lab in the online library, e.g. 03-ospf-multiarea).
  Leave `version:` out for a new lab (it defaults to "1"); raise it only when revising a published lab.
- Default to a challenge lab (`type` omitted). Only when the request asks for a guided, step-by-step build, write
  `type: walkthrough` with ordered `steps` (explain, config per device, verify with expected output, checks) and no
  lab-level checks, solution or faults (see "Walkthrough labs" in the guide).
- Mind CML server RAM: IOL nodes need about 1 GB each. Only use a `definition:` such as nxosv9000 (about 12 GB each,
  literal Ethernet1/1-1/4 names) when the request needs NX-OS, and say in the task how much RAM the lab needs.
  Set `ram_gb:` only if the estimate from the node types would be wrong. Labs from 16 GB up are tagged RAM heavy.
"""


def build_prompt(description: str | None = None, fmt: str = "yaml") -> str:
    desc = (description or "").strip() or PLACEHOLDER
    return "\n".join([
        "You are generating a Cisco CCNP ENCOR (350-401) practice lab for the 'CML Lab Builder' app,",
        "which builds the lab in Cisco Modeling Labs 2.9 and grades it automatically.",
        "",
        "## Lab request",
        desc,
        "",
        "## " + RULES.replace("YAML that follows", "YAML that follows" if fmt == "yaml" else "JSON that follows"),
        "## Check templates (machine-readable)",
        "```json", json.dumps(template_catalog(), indent=1), "```",
        "",
        "## Authoring guide",
        guide(),
        "",
        "## Example lab (valid; copy its structure)",
        "```yaml", example().rstrip(), "```",
        "",
        "## JSON Schema",
        "```json", json.dumps(json_schema(), indent=1), "```",
        "",
        "Now produce the lab for the request above." + (
            " Reply with one JSON object only." if fmt == "json" else " Reply with one ```yaml block only."),
    ])


DOC_HEADER = """\
# AI prompt for generating CML Lab Builder labs

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

"""


def docs_files() -> dict[str, str]:
    """Generated documentation files under docs/ (kept in sync by tests)."""
    return {
        "AI-PROMPT.md": DOC_HEADER + build_prompt(None),
        "encorlab-lab.schema.json": json.dumps(json_schema(), indent=2) + "\n",
        "LAB-AUTHORING.md": guide(),
        "example-lab.yaml": example(),
    }
