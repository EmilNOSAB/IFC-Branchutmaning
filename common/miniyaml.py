"""Minimal YAML subset parser.

MicroStation's bundled Python (PowerPlatformPython) does not ship PyYAML.  The
configuration files in config/ only use this subset, which this module parses:

* block mappings (``key: value``) and block sequences (``- item``),
  including sequences of mappings (``- key: value`` followed by indented keys)
* flow sequences ``[a, b, [c, d]]`` and flow mappings ``{a: 1, b: x}``
* plain, single- and double-quoted scalars, ints, floats, true/false, null/~
* ``#`` comments (outside quotes)

``load()`` uses PyYAML when it is installed and falls back to this parser.
tests/test_config.py checks that both give identical results for config/*.yaml.
"""

from __future__ import annotations

import re
from typing import Any, List, Tuple

_INT = re.compile(r"^[-+]?\d+$")
# PyYAML (YAML 1.1) requires a decimal point for floats: "60E1" stays a string
_FLOAT = re.compile(r"^[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?$")


class YamlError(ValueError):
    pass


def _strip_comment(line: str) -> str:
    out = []
    quote = None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        else:
            if ch in ("'", '"'):
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                break
            out.append(ch)
    return "".join(out).rstrip()


def _scalar(text: str) -> Any:
    t = text.strip()
    if t == "":
        return None
    if len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"'):
        body = t[1:-1]
        if t[0] == "'":
            return body.replace("''", "'")
        return (body.replace("\\\\", "\x00").replace('\\"', '"').replace("\\n", "\n")
                .replace("\\t", "\t").replace("\x00", "\\"))
    low = t.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~"):
        return None
    if _INT.match(t):
        return int(t)
    if _FLOAT.match(t):
        return float(t)
    return t


def _split_flow(body: str) -> List[str]:
    parts, depth, quote, cur = [], 0, None, []
    for ch in body:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if "".join(cur).strip():
        parts.append("".join(cur))
    return parts


def _split_key(text: str) -> Tuple[str, str]:
    """Split 'key: value' at the first ': ' (or trailing ':') outside quotes/brackets."""
    quote, depth = None, 0
    for i, ch in enumerate(text):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ":" and depth == 0 and (i + 1 == len(text) or text[i + 1] in " \t"):
            return text[:i].strip(), text[i + 1:].strip()
    raise YamlError("Expected 'key: value' in %r" % text)


def _value(text: str) -> Any:
    t = text.strip()
    if t.startswith("["):
        if not t.endswith("]"):
            raise YamlError("Unterminated flow sequence %r" % t)
        return [_value(p) for p in _split_flow(t[1:-1])]
    if t.startswith("{"):
        if not t.endswith("}"):
            raise YamlError("Unterminated flow mapping %r" % t)
        out = {}
        for p in _split_flow(t[1:-1]):
            k, v = _split_key(p.strip())
            out[_scalar(k)] = _value(v)
        return out
    return _scalar(t)


def _is_key_line(text: str) -> bool:
    try:
        _split_key(text)
        return True
    except YamlError:
        return False


def loads(text: str) -> Any:
    lines: List[Tuple[int, str]] = []
    for raw in text.splitlines():
        if raw.strip().startswith("#") or not raw.strip():
            continue
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise YamlError("Tabs are not allowed for indentation")
        s = _strip_comment(raw)
        if not s.strip():
            continue
        lines.append((len(s) - len(s.lstrip(" ")), s.strip()))
    pos = [0]

    def parse_block(indent: int) -> Any:
        if pos[0] >= len(lines):
            return None
        ind, txt = lines[pos[0]]
        if txt.startswith("- ") or txt == "-":
            return parse_seq(ind)
        return parse_map(ind)

    def parse_map(indent: int) -> dict:
        out = {}
        while pos[0] < len(lines):
            ind, txt = lines[pos[0]]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("Unexpected indentation at %r" % txt)
            if txt.startswith("- "):
                break
            k, v = _split_key(txt)
            pos[0] += 1
            key = _scalar(k)
            if v == "":
                if pos[0] < len(lines) and (lines[pos[0]][0] > ind or
                                            (lines[pos[0]][0] == ind and lines[pos[0]][1].startswith("- "))):
                    out[key] = parse_block(lines[pos[0]][0])
                else:
                    out[key] = None
            else:
                out[key] = _value(v)
        return out

    def parse_seq(indent: int) -> list:
        out = []
        while pos[0] < len(lines):
            ind, txt = lines[pos[0]]
            if ind < indent or not (txt.startswith("- ") or txt == "-"):
                break
            if ind > indent:
                raise YamlError("Unexpected indentation at %r" % txt)
            item = txt[1:].strip()
            if item == "":
                pos[0] += 1
                out.append(parse_block(lines[pos[0]][0]) if pos[0] < len(lines) and lines[pos[0]][0] > ind else None)
            elif not item.startswith(("[", "{", "'", '"')) and _is_key_line(item):
                # mapping inside a sequence item: re-insert the first key line at item indentation
                item_indent = ind + (len(txt) - len(item))
                lines[pos[0]] = (item_indent, item)
                out.append(parse_map(item_indent))
            else:
                pos[0] += 1
                out.append(_value(item))
        return out

    result = parse_block(lines[0][0]) if lines else None
    if pos[0] != len(lines):
        raise YamlError("Could not parse line %r" % (lines[pos[0]][1],))
    return result


def load(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # type: ignore
    except ImportError:
        return loads(text)
    return yaml.safe_load(text)
