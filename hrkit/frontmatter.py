"""Minimal YAML-ish frontmatter parser/writer (stdlib only)."""
from __future__ import annotations
import json
from typing import Any


def parse(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm_raw = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    return _parse_yaml(fm_raw), body


def dump(fm: dict, body: str = "") -> str:
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {_serialize(v)}")
    lines.append("---")
    out = "\n".join(lines)
    if body:
        out += "\n\n" + body.lstrip("\n")
    if not out.endswith("\n"):
        out += "\n"
    return out


def _parse_yaml(raw: str) -> dict:
    out: dict = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = _coerce(v.strip())
    return out


def _coerce(v: str) -> Any:
    if v == "" or v == "~" or v.lower() == "null":
        return ""
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        return v[1:-1]
    if len(v) >= 2 and v[0] == "'" and v[-1] == "'":
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [s.strip().strip('"').strip("'") for s in inner.split(",") if s.strip()]
    try:
        if "." in v:
            return float(v)
        return int(v)
    except ValueError:
        pass
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    return v


def _serialize(v: Any) -> str:
    if v is None or v == "":
        return '""'
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        parts = []
        for x in v:
            if isinstance(x, str):
                parts.append(json.dumps(x))
            else:
                parts.append(str(x))
        return "[" + ", ".join(parts) + "]"
    s = str(v)
    if any(c in s for c in ':#{}[]\n"\''):
        return json.dumps(s)
    return f'"{s}"'
