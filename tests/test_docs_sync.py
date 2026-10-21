from pathlib import Path

from cmllab.prompt import docs_files

DOCS = Path(__file__).parent.parent / "docs"


def test_docs_are_generated_and_current():
    for name, text in docs_files().items():
        f = DOCS / name
        assert f.is_file(), f"missing {f}; run python -m cmllab docs"
        assert f.read_text(encoding="utf-8") == text, f"{name} is stale; run python -m cmllab docs"
