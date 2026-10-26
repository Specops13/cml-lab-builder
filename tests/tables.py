"""Table-driven tests: one test item runs every row and reports all failing rows at once.

    from tables import run_table
    def _case(a, b): assert f(a) == b
    def test_f(): run_table(_case, [(1, 2), (3, 4)])

Use this instead of @pytest.mark.parametrize for cheap pure-function tables (keeps the test count meaningful)."""
from __future__ import annotations


def run_table(fn, rows, single: bool = False) -> None:
    fails = []
    for row in rows:
        args = (row,) if single or not isinstance(row, tuple) else row
        try:
            fn(*args)
        except Exception as e:          # AssertionError and anything the row raises
            fails.append(f"{row!r}: {type(e).__name__}: {e}")
    assert not fails, f"{len(fails)}/{len(rows)} rows failed:\n" + "\n".join(fails)
