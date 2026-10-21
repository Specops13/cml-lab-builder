"""Progress dashboard: mastery per study track (ENCOR, CCNA, ... from each lab's `track:`), per ENCOR exam domain and
per topic, streaks, time spent, weakest topics.

Inputs are the per-lab results histories (history.py). Rules (documented in the README):
* attempt score = score_pct - HINT_PENALTY per hint used (exam attempts use their final exam score)
* a revealed fault/solution counts as at most REVEALED_CAP
* lab mastery = best attempt score; track/domain/topic mastery = average lab mastery over the labs mapped to it
  (labs never checked count as 0); the ENCOR overall mastery is weighted by the exam domain weights and uses only
  ENCOR labs; with other tracks too, overall mastery is the average over all labs
* time spent per lab is estimated from the lab timer value sent with each Check
* walkthrough labs are guided builds, not graded: they are listed separately (steps passed, completed) and never
  count towards mastery, solved labs or streaks"""
from __future__ import annotations

import datetime as dt
from collections import Counter

from . import blueprint, catalog, history

HINT_PENALTY = 5.0
REVEALED_CAP = 50.0


def attempt_score(h: dict) -> float:
    if isinstance(h.get("exam"), dict) and h["exam"].get("final_pct") is not None:
        return float(h["exam"]["final_pct"])
    s = float(h.get("score_pct") or 0) - HINT_PENALTY * float(h.get("hints_used") or 0)
    if h.get("revealed"):
        s = min(s, REVEALED_CAP)
    return max(0.0, round(s, 1))


def lab_time(hist: list[dict]) -> int:
    """Sum of timer increments: the timer value grows within a session and drops when it is reset."""
    total, last = 0, 0
    for h in hist:
        e = h.get("elapsed_s")
        if not isinstance(e, (int, float)) or e < 0:
            continue
        total += e - last if e >= last else e
        last = e
    return int(total)


def _day(ts: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(str(ts)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def streaks(days: set[dt.date], today: dt.date) -> dict:
    if not days:
        return {"current": 0, "longest": 0, "active_days": 0, "last_day": None}
    longest, run, prev = 0, 0, None
    for d in sorted(days):
        run = run + 1 if prev and (d - prev).days == 1 else 1
        longest, prev = max(longest, run), d
    cur, d = 0, today if today in days else today - dt.timedelta(days=1)
    while d in days:
        cur, d = cur + 1, d - dt.timedelta(days=1)
    return {"current": cur, "longest": longest, "active_days": len(days), "last_day": max(days).isoformat()}


def compute(today: dt.date | None = None, entries: dict | None = None, histories: dict | None = None,
            walkthroughs: dict | None = None) -> dict:
    """walkthroughs: lab id -> walkthrough.status() (default: read from the data folder)."""
    today = today or dt.date.today()
    entries = entries if entries is not None else catalog.entries()
    histories = histories if histories is not None else {lid: history.load(lid) for lid in entries}
    labs, days, recent, failed = [], set(), [], Counter()
    check_desc: dict[tuple[str, str], str] = {}
    walks = []
    for lid, e in entries.items():
        if e.lab.is_walkthrough:
            if walkthroughs is not None and lid in walkthroughs:
                st = walkthroughs[lid]
            else:
                from . import walkthrough
                st = walkthrough.status(e.lab)
            walks.append({"id": lid, "title": e.lab.title, "blueprint": e.lab.blueprint, "source": e.source,
                          "steps": len(e.lab.steps), "required": st["required"],
                          "required_passed": st["required_passed"], "pct": st["pct"],
                          "completed": bool(st["completed"]), "completed_at": st["completed"],
                          "started": any(x.get("passed") is not None for x in st["steps"]) or st["current"] > 0})
            continue
        h = histories.get(lid, [])
        for c in [c for st in e.lab.steps for c in st.checks] + e.lab.checks + [c for f in e.lab.faults for c in f.checks]:
            check_desc[(lid, c.id)] = c.description
        for x in h:
            d = _day(x.get("ts", ""))
            if d:
                days.add(d)
            failed.update((lid, cid) for cid in x.get("failed", []))
            recent.append({"lab_id": lid, "title": e.lab.title, "ts": x.get("ts"), "score_pct": x.get("score_pct"),
                           "adjusted_pct": attempt_score(x), "passed": x.get("passed"),
                           "kind": "exam" if x.get("exam") else "fault" if x.get("fault") else "lab"})
        labs.append({"id": lid, "title": e.lab.title, "blueprint": e.lab.blueprint, "source": e.source,
                     "track": e.lab.track,
                     "attempts": len(h), "solved": any(x.get("passed") for x in h),
                     "mastery_pct": max((attempt_score(x) for x in h), default=0.0),
                     "faults_fixed": sum(1 for x in h if x.get("fault") and x.get("passed")),
                     "time_s": lab_time(h), "last": h[-1]["ts"] if h else None})

    def agg(members: list[dict]) -> dict:
        n = len(members)
        return {"labs": n, "attempted": sum(1 for m in members if m["attempts"]),
                "solved": sum(1 for m in members if m["solved"]),
                "mastery_pct": round(sum(m["mastery_pct"] for m in members) / n, 1) if n else None}

    tracks = []
    for t in sorted({l["track"] for l in labs}, key=lambda t: (t.upper() != "ENCOR", t.lower())):
        members = [l for l in labs if l["track"] == t]
        tracks.append({"id": t, **agg(members), "lab_ids": [m["id"] for m in members],
                       "encor": t.upper() == "ENCOR"})
    encor = [l for l in labs if l["track"].upper() == "ENCOR"]
    domains = []
    for did, (name, weight) in blueprint.DOMAINS.items():
        members = [l for l in encor if any(blueprint.domain_of(b) == did for b in l["blueprint"])]
        domains.append({"id": did, "name": name, "weight": weight, **agg(members), "lab_ids": [m["id"] for m in members]})
    items = []
    for item in sorted({b for l in labs for b in l["blueprint"]}, key=lambda s: [int(p) if p.isdigit() else p for p in s.split(".")]):
        members = [l for l in labs if item in l["blueprint"]]
        enc = all(m["track"].upper() == "ENCOR" for m in members)
        items.append({"id": item, "title": blueprint.title(item) if enc else "", "domain": blueprint.domain_of(item) if enc else None,
                      "track": members[0]["track"] if len({m["track"] for m in members}) == 1 else "",
                      **agg(members), "lab_ids": [m["id"] for m in members]})
    covered = [d for d in domains if d["labs"]]
    wsum = sum(d["weight"] for d in covered)
    encor_overall = round(sum(d["weight"] * d["mastery_pct"] for d in covered) / wsum, 1) if wsum else 0.0
    if len(tracks) > 1 or (tracks and not tracks[0]["encor"]):
        overall = round(sum(l["mastery_pct"] for l in labs) / len(labs), 1)
    else:
        overall = encor_overall
    weakest = sorted(items, key=lambda i: (i["mastery_pct"], -i["labs"]))[:5]
    recent.sort(key=lambda r: r["ts"] or "", reverse=True)
    activity = []
    counts = Counter(_day(r["ts"] or "") for r in recent)
    for i in range(29, -1, -1):
        d = today - dt.timedelta(days=i)
        activity.append({"day": d.isoformat(), "checks": counts.get(d, 0)})
    return {
        "blueprint": blueprint.VERSION,
        "overall": {"mastery_pct": overall, "labs_total": len(labs), "labs_attempted": sum(1 for l in labs if l["attempts"]),
                    "labs_solved": sum(1 for l in labs if l["solved"]), "checks_run": len(recent),
                    "faults_fixed": sum(l["faults_fixed"] for l in labs), "time_spent_s": sum(l["time_s"] for l in labs),
                    "uncovered_domains": [d["id"] for d in domains if not d["labs"]],
                    "encor_mastery_pct": encor_overall, "encor_labs": len(encor)},
        "tracks": tracks,
        "streak": streaks(days, today),
        "domains": domains, "items": items, "labs": labs, "weakest": weakest,
        "walkthroughs": {"labs": walks, "total": len(walks), "completed": sum(1 for w in walks if w["completed"]),
                         "started": sum(1 for w in walks if w["started"])},
        "failed_checks": [{"lab_id": lid, "check_id": cid, "description": check_desc.get((lid, cid), cid), "count": n}
                          for (lid, cid), n in failed.most_common(5)],
        "recent": recent[:10], "activity": activity,
        "rules": {"hint_penalty": HINT_PENALTY, "revealed_cap": REVEALED_CAP},
    }
