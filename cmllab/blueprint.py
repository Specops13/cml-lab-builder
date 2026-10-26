"""ENCOR 350-401 exam topics (from the exam registry, cmllab/exams/encor.yaml: Cisco's published blueprint), used to map labs to domains for the progress dashboard."""
from __future__ import annotations

from . import objectives

_ENCOR = objectives.registry()["ENCOR"]      # cmllab/exams/encor.yaml (Cisco's published 350-401 exam topics)
VERSION = f"{_ENCOR.code} ENCOR {_ENCOR.version}"

DOMAINS: dict[str, tuple[str, int]] = {k: (n, int(w or 0)) for k, (n, w) in _ENCOR.domains.items()}  # id -> (name, weight %)

ITEMS: dict[str, str] = dict(_ENCOR.objectives)


def domain_of(item: str) -> str | None:
    d = item.split(".")[0] + ".0"
    return d if d in DOMAINS else None


def title(item: str) -> str:
    return ITEMS.get(item) or ITEMS.get(".".join(item.split(".")[:2]), "")


def known(item: str) -> bool:
    return item in ITEMS
