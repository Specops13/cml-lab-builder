"""Optional AI lab generator using any OpenAI-compatible /chat/completions API
(xAI, OpenAI, Ollama, LM Studio, ...). Generated labs are validated with the
same strict linter as `cmllab pack`; validation errors are fed back for up to
2 retries. Nothing is saved automatically: the result opens in the builder."""
from __future__ import annotations

import json
import re

import httpx
import yaml

from .packs import Pack, lint
from .prompt import build_prompt

PRESETS = {
    "xai": {"label": "xAI", "base_url": "https://api.x.ai/v1", "model": "grok-4", "needs_key": True},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1", "needs_key": True},
    "ollama": {"label": "Ollama (local)", "base_url": "http://localhost:11434/v1", "model": "llama3.1", "needs_key": False},
    "lmstudio": {"label": "LM Studio (local)", "base_url": "http://localhost:1234/v1", "model": "local-model", "needs_key": False},
}

KEYRING_PREFIX = "ai-key:"


class AIError(RuntimeError):
    pass


def extract_lab(content: str) -> dict:
    """Accept a JSON object, a ```json / ```yaml block, or bare YAML."""
    text = content.strip()
    m = re.search(r"```(?:json|yaml|yml)?\s*\n(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise AIError(f"response is neither JSON nor YAML: {e}")
    if isinstance(data, dict) and isinstance(data.get("lab"), dict) and "id" not in data:
        data = data["lab"]
    if not isinstance(data, dict):
        raise AIError("response did not contain a lab object")
    return data


def to_yaml_text(data: dict) -> str:
    class D(yaml.SafeDumper):
        pass

    def s(dumper, v):
        return dumper.represent_scalar("tag:yaml.org,2002:str", v, style="|" if "\n" in v else None)
    D.add_representer(str, s)
    return yaml.dump(data, Dumper=D, sort_keys=False, allow_unicode=True, width=1000)


def chat(base_url: str, model: str, api_key: str | None, messages: list[dict], json_mode: bool = True,
         timeout: float = 180.0, transport=None) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = base_url.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=timeout, transport=transport) as c:
        r = c.post(url, headers=headers, json=body)
        if r.status_code == 400 and json_mode:  # some servers don't support response_format
            body.pop("response_format")
            r = c.post(url, headers=headers, json=body)
    if r.status_code == 401:
        raise AIError("the AI provider rejected the API key (401)")
    if r.status_code >= 400:
        raise AIError(f"AI provider error {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except Exception:
        raise AIError(f"unexpected response from AI provider: {r.text[:300]}")


def generate(description: str, base_url: str, model: str, api_key: str | None, node_limit: int = 20,
             max_retries: int = 2, transport=None, progress=lambda m: None) -> dict:
    if not description.strip():
        raise AIError("describe the lab you want")
    messages = [
        {"role": "system", "content": build_prompt(None, fmt="json").replace(
            "## Lab request\n{{DESCRIBE YOUR LAB HERE: topic, devices, difficulty, blueprint items}}\n", "")},
        {"role": "user", "content": f"Lab request: {description.strip()}\nReply with one JSON object (the lab)."},
    ]
    attempts = []
    for attempt in range(1, max_retries + 2):
        progress(f"Asking {model} (attempt {attempt})")
        content = chat(base_url, model, api_key, messages, transport=transport)
        errors: list[str]
        lab_yaml = None
        try:
            data = extract_lab(content)
            lab_yaml = to_yaml_text(data)
            rep = lint(Pack(lab_yaml), node_limit=node_limit, strict=True)
            errors, warnings = rep.errors, rep.warnings
        except AIError as e:
            errors, warnings, rep = [str(e)], [], None
        attempts.append({"attempt": attempt, "errors": errors, "warnings": warnings})
        if not errors:
            progress("Lab validated: solution 100%, starting config fails")
            return {"ok": True, "lab_yaml": lab_yaml, "report": rep.to_dict(), "attempts": attempts}
        progress(f"Validation failed ({len(errors)} errors); asking for a fix")
        messages.append({"role": "assistant", "content": content})
        messages.append({"role": "user", "content": "The lab failed validation. Fix ALL of these errors and reply with "
                         "the complete corrected lab as one JSON object:\n- " + "\n- ".join(errors[:30])})
    return {"ok": False, "lab_yaml": lab_yaml, "report": rep.to_dict() if rep else None, "attempts": attempts}
