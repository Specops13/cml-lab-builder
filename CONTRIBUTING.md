# Contributing to CML Lab Builder

## Setup
```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q -n auto -m "not slow"   # fast set
.venv/bin/python -m pytest -q -n auto                 # full suite incl. @slow end-to-end tests
ruff check cmllab cmlboot.py cmllab_launcher.py tests && python packaging/build_patch.py --check-lock
```

## Adding a lab (library)
1. Create `examples/<id>/lab.yaml` (or `labsrc/<id>/`), with `fixture_solved.yaml` and `fixture_blank.yaml`. See
   [docs/LAB-AUTHORING.md](docs/LAB-AUTHORING.md). Walkthroughs are preferred. Checks use only `show`/`ping`, and debug commands go in
   the explanation text.
2. **IOL day-0 rule:** every Ethernet port of every `iol-xe` node has IP config in the starting config (at least
   `no ip address`), plus a description and `shutdown`/`no shutdown`. NX-OS day-0 turns off domain lookup and adds the
   admin user.
3. **Exam objectives:** add `exams.yaml` next to `lab.yaml`, with `lab:` (lab-level tags) and `steps:` (per step id).
   Tags are `<EXAM> <objective>` as in Cisco's exam topics (`ENCOR 3.2.b`). Use `python -m cmllab exams --suggest
   <blueprint items> --track <TRACK>` for ideas, and `python -m cmllab exams --coverage` to find gaps worth a new lab.
   Tag only what the student configures or verifies. A lab without tags gets a lint warning with suggestions, and
   `packaging/build_library.py` refuses it.
4. Add the lab's topics in `labsrc/library.yaml`, run `python packaging/build_library.py` (raise `version:` when the
   content changes), then `python packaging/build_library.py --check`.
5. Check it: `python -m cmllab validate examples/<id>` (strict lint: solution 100 %, blank start not solved).

## Tests: how they are laid out
The suite is table-driven. A new lab needs **no new test**:
- `tests/test_lab_content.py::test_library_lab[<id>]` runs the generic validator over every library lab. It covers lint
  in both grading modes, exam tags, the pack and both indexes, older-app compatibility, the day-0 rules, challenge faults
  and hints, and every walkthrough step's checks in the simulator.
- Optional: add a `spec_<n>(lab)` function to `SPECS` in that file for 0 to 2 lab-specific facts you want pinned (for example
  "the hub has no static NHRP maps").
- `tests/tables.py` has `run_table(fn, rows)` for any other repeated check: one test, every failing row reported.
- Mark a test `@pytest.mark.slow` if it takes more than a second or two (real sockets, threads, timeouts, pack
  rebuilds). Slow tests still run in the full suite.
- Do not trim the security, update/signing, day-0 or resource-check tests.

## Adding an exam
Add `cmllab/exams/<id>.yaml` (see `encor.yaml`): `id`, `code`, `name`, `version`, `level`, `source` (the official Cisco
exam-topics URL), `published`, `fetched`, `domains` and `objectives`, transcribed exactly. Never invent objective numbers. If the
blueprint cannot be fetched, leave the exam out. `tests/test_exams.py` validates the file.

## Releases
Version in `cmllab/__init__.py`, `pyproject.toml` and `app.js` (`APP_JS_VERSION`), plus README and CHANGELOG in the same
commit. Push `main` first and the `v*` tag last, never force-push. CI builds the bundles, patch and .deb on the tag, and
the maintainer signs `SHA256SUMS.txt` and the patch locally (see SECURITY.md).
