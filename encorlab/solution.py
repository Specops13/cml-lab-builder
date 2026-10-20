"""Solution summary + progressive hints, shared by the CLI and the web UI.

`solution_summary` (Markdown) is written by the lab author; when a lab has none, a fallback
is generated from the reference solution (per device: the lines to add)."""
from __future__ import annotations

from .platforms import Platform, render
from .schema import Lab


def fallback_summary(solution: dict[str, str]) -> str:
    if not solution:
        return "_This lab has no reference solution._\n"
    out = ["**Fix (auto-generated from the reference solution):** add these lines on each device.", ""]
    for dev, cfg in solution.items():
        out += [f"**{dev}**", "```", cfg.rstrip(), "```", ""]
    return "\n".join(out)


def summary(lab: Lab, solution: dict[str, str], plat: Platform) -> tuple[str, bool]:
    """(rendered Markdown, auto_generated)."""
    if lab.solution_summary.strip():
        return render(lab.solution_summary, plat), False
    return render(fallback_summary(solution), plat), True


def reveal(lab: Lab, solution: dict[str, str], plat: Platform) -> dict:
    text, auto = summary(lab, solution, plat)
    return {"summary": text, "auto_generated": auto,
            "configs": {dev: render(cfg, plat) for dev, cfg in solution.items()}}


def hints(lab: Lab, plat: Platform) -> list[str]:
    """Ordered hints: lab-level `hints`, else the per-check hints in check order (duplicates dropped)."""
    if lab.hints:
        src = lab.hints
    else:
        src, seen = [], set()
        for c in lab.graded_checks:
            if c.hint and c.hint not in seen:
                seen.add(c.hint)
                src.append(c.hint)
    return [render(h, plat) for h in src]


def text_report(lab: Lab, solution: dict[str, str], plat: Platform) -> str:
    """Plain-text (Markdown) solution for the CLI."""
    s = reveal(lab, solution, plat)
    out = [f"# Solution: {render(lab.title, plat)}", "", s["summary"].rstrip(), ""]
    if s["configs"] and not s["auto_generated"]:
        out += ["## Solution config (lines to add)", ""]
        for dev, cfg in s["configs"].items():
            out += [f"! device {dev}", cfg.rstrip(), ""]
    return "\n".join(out)
