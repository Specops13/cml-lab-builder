"""Regenerate the day-0 configs of the NX-OS study path labs 22 and 23 (examples/22-..., examples/23-...).

Each lab is its own CML lab that boots from its own baseline: lab N's node configs = lab N-1's node configs (without
their leading `!` comment) + every required step of lab N-1 (optional steps are not carried over). The nodes section
of lab N's lab.yaml (between `nodes:` and `links:`) is rewritten; everything else is left alone.
tests/test_nxos_study_path.py fails if a baseline drifts from this rule.
Usage: python packaging/nxos_study_baseline.py [--check]"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cmllab import packs  # noqa: E402

SERIES = ["21-nxos-ospf-multiarea", "22-nxos-bgp-over-ospf", "23-nxos-evpn-vxlan"]
DONE = {"22-nxos-bgp-over-ospf": "lab 21 (OSPF multi-area)", "23-nxos-evpn-vxlan": "lab 22 (iBGP over OSPF)"}


def _lab(lab_id):
    return packs.parse_lab_text((ROOT / "examples" / lab_id / "lab.yaml").read_text(encoding="utf-8"))[0]


def body(cfg: str) -> str:
    """A node config without its leading comment lines."""
    lines = cfg.splitlines()
    while lines and lines[0].lstrip().startswith("!"):
        lines.pop(0)
    return "\n".join(lines).rstrip() + "\n"


def baseline(prev, lab_id: str) -> dict[str, str]:
    sol = prev.step_solution(include_optional=False)
    n = lab_id[:2]
    out = {}
    for node in prev.nodes:
        if node.name not in sol:                     # hosts: unchanged
            out[node.name] = node.config.rstrip() + "\n"
            continue
        head = (f"! Lab {n} baseline (the start of this lab) = the lab {int(n) - 1} baseline + every required step of "
                f"{DONE[lab_id]}. CML builds this lab fresh from this config; it never reuses an earlier lab.\n")
        out[node.name] = head + body(node.config) + sol[node.name]
    return out


def nodes_yaml(prev, cfgs: dict[str, str]) -> str:
    out = ["nodes:"]
    for node in prev.nodes:
        out += [f"  - name: {node.name}", f"    kind: {node.kind}"]
        if node.definition:
            out.append(f"    definition: {node.definition}")
        out += [f"    x: {node.x}", f"    y: {node.y}", "    config: |"]
        out += [("      " + l) if l.strip() else "" for l in cfgs[node.name].rstrip("\n").split("\n")]
    return "\n".join(out) + "\n"


def main() -> None:
    stale = []
    for prev_id, lab_id in zip(SERIES, SERIES[1:]):
        p = ROOT / "examples" / lab_id / "lab.yaml"
        if not p.is_file():
            continue
        prev = _lab(prev_id)
        text = p.read_text(encoding="utf-8")
        a, b = text.index("\nnodes:\n") + 1, text.index("\nlinks:\n") + 1
        new = text[:a] + nodes_yaml(prev, baseline(prev, lab_id)) + text[b:]
        if new != text:
            stale.append(lab_id)
            if "--check" not in sys.argv:
                p.write_text(new, encoding="utf-8")
                print(f"rewrote the baseline of {lab_id}")
    if "--check" in sys.argv and stale:
        sys.exit(f"baselines out of date: {stale} (run python packaging/nxos_study_baseline.py)")


if __name__ == "__main__":
    main()
