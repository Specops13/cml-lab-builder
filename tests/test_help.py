"""Every interactive control in the web UI must carry help text, and all help text lives in help.json."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from cmllab import config
from cmllab.web.app import create_app

WEB = Path(__file__).parent.parent / "cmllab" / "web"
HELP = json.loads((WEB / "static" / "help.json").read_text(encoding="utf-8"))
SOURCES = {"index.html": (WEB / "templates" / "index.html").read_text(encoding="utf-8"),
           "app.js": (WEB / "static" / "app.js").read_text(encoding="utf-8")}
INTERACTIVE = re.compile(r"<(button|input|select|textarea|a|summary)\b(?!\s+data-help)")
KEY_ATTR = re.compile(r'data-help="([\w.]+)"')
FIELD_KEY = re.compile(r'\bfield\("([\w.]+)"')


def test_every_interactive_control_has_help():
    missing = []
    for name, text in SOURCES.items():
        for m in INTERACTIVE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            missing.append(f"{name}:{line}: <{m.group(1)}> without data-help / data-help-text")
        for m in re.finditer(r"<li\b[^>]*\bdata-id\b[^>]*>", text):  # clickable list items
            if "data-help" not in m.group(0):
                missing.append(f"{name}: clickable <li> without data-help")
    # the field() helper must always be given a help key
    assert "const field = (help," in SOURCES["app.js"]
    calls = re.findall(r"\bfield\(([^)]*)", SOURCES["app.js"].split("const field =", 1)[1])
    missing += [f"app.js: field({c[:40]}...) without help key" for c in calls if not FIELD_KEY.match("field(" + c)]
    assert not missing, "\n".join(missing)


def test_help_keys_exist_and_are_used():
    used = set()
    for text in SOURCES.values():
        used |= set(KEY_ATTR.findall(text)) | set(FIELD_KEY.findall(text))
    keys = {k for k in HELP if not k.startswith("_")}
    assert not used - keys, f"help keys missing in help.json: {sorted(used - keys)}"
    assert not keys - used, f"unused help keys (remove or wire up): {sorted(keys - used)}"


def test_help_texts_are_short():
    for k, v in HELP.items():
        if k.startswith("_"):
            continue
        assert v.strip() and len(v) <= 220, f"{k}: keep help to 1-2 short sentences"
        sentences = re.findall(r"[.!?](?:\s|$)", re.sub(r"\b(e\.g|i\.e|etc)\.", "x", v))
        assert len(sentences) <= 2, f"{k}: {len(sentences)} sentences"


def test_page_loads_help_engine_and_toggle_setting():
    s = config.Settings()
    c = TestClient(create_app(config.SettingsStore(s), persist=False))
    html = c.get("/").text
    assert 'src="/static/help.js?v=' in html and 'id="tooltip" role="tooltip"' in html and 'name="show_help"' in html
    assert c.get("/static/help.json").json()["lab.build"]
    js = c.get("/static/help.js").text
    assert "300" in js and "Escape" in js and "aria-describedby" in js
    assert "pointer-events:none" in c.get("/static/style.css").text.replace(" ", "")
    assert c.get("/api/settings").json()["show_help"] is True
    assert c.post("/api/settings", json={"show_help": False}).json()["show_help"] is False


def test_show_help_persisted_in_settings_json(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    monkeypatch.setenv("CMLLAB_SETTINGS_FILE", str(f))
    store = config.SettingsStore(config.Settings())
    config.save_settings(store.update(show_help=False))
    assert json.loads(f.read_text(encoding="utf-8"))["show_help"] is False
    assert config.from_env().show_help is False
