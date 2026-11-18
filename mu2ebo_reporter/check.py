"""Flag every number in a report that no tool output contains."""
from __future__ import annotations

import json
import math
import re
from itertools import permutations
from typing import Any

DASHES = str.maketrans({"\u2011": "-", "\u2212": "-", "\u2010": "-", "\u2013": "-"})
SUP = str.maketrans("\u207b\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079", "-0123456789")
NUM = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:\s*[x\u00d7]\s*10-?\d+|\s?[eE][-+]?\d+)?")
HDR_SCALE = re.compile(r"\(\s*[x\u00d7]\s*10-\d+\s*\)")
SCALE = re.compile(r"[x\u00d7]\s*10-(\d+)")
IGNORE = re.compile(r"\b[A-Za-z]+\d+R\d+_\d+\b"            # config names
                    r"|\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?"    # dates
                    r"|(?:DocDB|docdb)[\s-]*\d+"            # document numbers
                    r"|/[\w./-]+"                           # paths
                    r"|\b[A-Za-z]+_\d+\b")                  # knob names like rOut_0
DOCREF = re.compile(r"DocDB|docdb")
PCT = re.compile(r"\s*(?:%|percent\b)")
TOK = re.compile(r"-?\d+(?:\.(\d+))?(?:\s*[x\u00d7]\s*10(-?\d+)|\s?[eE]([-+]?\d+))?")
PROVENANCE_MARK = "\n\n## Provenance\n\n- Data root: "  # how agent.join_report appends the program's section


def model_text(report: str) -> str:
    """A stored report without the Provenance section the program appended (it names the model id)."""
    return report.rsplit(PROVENANCE_MARK, 1)[0]


def norm(text: str) -> str:
    return re.sub(r"[\u00a0\u2009\u202f]", " ", text.translate(DASHES).translate(SUP))


def known_numbers(obj: Any, acc: list[float]) -> list[float]:
    if isinstance(obj, bool) or obj is None:
        return acc
    if isinstance(obj, (int, float)):
        if math.isfinite(obj):
            acc.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            known_numbers(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            known_numbers(v, acc)
    elif isinstance(obj, str):
        try:
            known_numbers(json.loads(obj), acc)
        except (ValueError, TypeError):
            s = norm(obj).replace("\u00d710-", "e-").replace("\u00d710", "e")
            acc.extend(float(m) for m in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", s))
    return acc


def parse(tok: str) -> float:
    m = re.match(r"(-?\d+(?:\.\d+)?)\s*[x\u00d7]\s*10(-?\d+)", tok)
    return float(m.group(1)) * 10 ** int(m.group(2)) if m else float(tok.replace(" ", ""))


def match(v: float, known: list[float]) -> float | None:
    """The known number closest to v, if any is close enough."""
    places = len(str(abs(v)).split(".")[1]) if "." in str(abs(v)) and abs(v) < 1e15 else 0
    tol = 0.5 * 10 ** -places if places else 0.5
    hits = [k for k in known if math.isclose(v, k, rel_tol=5e-3) or abs(v - k) <= tol]
    return min(hits, key=lambda k: abs(v - k)) if hits else None


def matches(v: float, known: list[float]) -> bool:
    return match(v, known) is not None


def printed_tol(tok: str) -> float:
    """Half a unit in the last printed digit: 45 -> 0.5, 7.4 -> 0.05, 1.2e-06 -> 5e-08."""
    m = TOK.match(tok)
    return 0.5 * 10 ** (int(m.group(2) or m.group(3) or 0) - len(m.group(1) or ""))


def derive(v: float, tok: str, pct: bool, inputs: list[tuple[str, tuple[float, ...]]]) -> str | None:
    """How v follows from two supported numbers of its line, or None.

    A difference a - b, or for a number printed with %: a percentage 100 a / b or a percentage change 100 (a - b) / b;
    otherwise a ratio a / b. Signs are dropped ("7.4 % lower"). Each input counts as printed and as the known number it
    matched, and the result must agree to its printed precision (no relative slack)."""
    tol, target = printed_tol(tok), abs(v)
    for (ta, xs), (tb, ys) in permutations(inputs, 2):
        for a in xs:
            for b in ys:
                ops = [("{a} - {b}", a - b)]
                if b:
                    ops += [("100 * {a} / {b}", 100 * a / b), ("100 * ({a} - {b}) / {b}", 100 * (a - b) / b)] \
                        if pct else [("{a} / {b}", a / b)]
                for how, c in ops:
                    if abs(abs(c) - target) <= tol:
                        return how.format(a=ta, b=tb)
    return None


def check(report: str, facts: Any) -> dict[str, Any]:
    known = known_numbers(facts, [])
    logs = [-math.log10(k) for k in known if k > 0]  # the surrogate's -log10 objective axes
    known += [-k for k in known] + [100 * k for k in known] + logs
    unsupported, docdb, derived, n, scale = [], [], [], 0, 0
    for raw in report.splitlines():
        line = norm(raw)
        table = line.lstrip().startswith("|")
        if table and SCALE.search(line) and HDR_SCALE.search(line):
            scale = int(SCALE.search(line).group(1))
        elif not table:
            scale = 0
        clean = IGNORE.sub(" ", HDR_SCALE.sub(" ", line) if table else line)
        toks = []
        for m in NUM.finditer(clean):
            tok, v = m.group(), parse(m.group())
            k = match(v, known)
            if k is None and scale and (k := match(v * 10 ** -scale, known)) is not None:
                k *= 10 ** scale  # in the column's printed units
            toks.append((tok, v, k, bool(PCT.match(clean, m.end()))))
        inputs = [(tok, (v, k)) for tok, v, k, _ in toks if k is not None]  # supported numbers of this line
        for tok, v, k, pct in toks:
            if float(v).is_integer() and abs(v) < 10:
                continue  # ranks, list indices, section numbers
            n += 1
            if k is not None:
                continue
            entry = {"value": tok, "line": raw.strip()[:200]}
            if how := derive(v, tok, pct, inputs):
                derived.append({**entry, "from": how})
                continue
            (docdb if DOCREF.search(line) else unsupported).append(entry)
    return {"numbers_checked": n, "unsupported": unsupported, "docdb_lines": docdb, "derived": derived,
            "ok": not unsupported}


def render(result: dict[str, Any]) -> str:
    lines = [f"numbers checked: {result['numbers_checked']}  unsupported: {len(result['unsupported'])}  "
             f"on DocDB lines (verify by hand): {len(result['docdb_lines'])}"]
    lines += [f"  UNSUPPORTED {u['value']!r}: {u['line']}" for u in result["unsupported"]]
    lines += [f"  DOCDB {u['value']!r}: {u['line']}" for u in result["docdb_lines"]]
    lines += [f"  derived {u['value']!r} = {u['from']}: {u['line']}" for u in result.get("derived", [])]
    return "\n".join(lines)
