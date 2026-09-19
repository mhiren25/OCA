#!/usr/bin/env python3
"""Scaffold corpus fixture directories from redacted .eml files.

    python scripts/scaffold_fixture.py corpus/staging/*.eml -o corpus/fixtures/

RUN THIS ON REDACTED EMAIL, NOT ORIGINALS.
Provenance offsets are computed against the body text in source.eml. Scaffold
first and redact after, and every offset past the first replacement shifts —
a corpus of subtly wrong spans, which is worse than no spans at all.

WHAT THIS DOES AND DOES NOT DO

It finds *spans* — the tedious, mechanical part. Character offsets for every
plausible anchor, computed exactly.

It does NOT decide *meaning*. Every field comes out UNRESOLVED with a
`_candidates` list beside it. You promote a candidate into a real value, or
delete it. That asymmetry is deliberate: if the scaffolder guessed values and
a tired human skimmed rather than read, you would end up with a corpus of
machine guesses wearing the authority of human labels — and every eval
afterwards would be measuring the model against a slightly worse version of
itself.

So: the script saves you the typing. It must never save you the thinking.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from email import policy
from email.parser import BytesParser
from pathlib import Path

# ---------------------------------------------------------------- anchors ---
# Deliberately over-inclusive. A false candidate costs one keystroke to
# delete; a missed one costs a hand-counted offset.

ANCHORS: dict[str, re.Pattern[str]] = {
    "side":       re.compile(r"\b(buy|bought|purchase|sell|sold|dispose|redeem)\w*\b", re.I),
    "quantity":   re.compile(r"\b(all|entire|whole|everything)\b|\b\d[\d,\.]{1,15}\b", re.I),
    "order_type": re.compile(r"\b(mkt|market|limit|lmt|at\s+best)\b", re.I),
    "strategy":   re.compile(r"\b(vwap|twap|pov|close|open|iceberg|dark)\b", re.I),
    "horizon":    re.compile(r"\b(over\s+the\s+day|today|day\s+order|gtc|gtd|good\s+till|fok|ioc)\b", re.I),
    "instrument": re.compile(
        r"\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"          # Bloomberg ticker
        r"|\b[A-Z]{2}[A-Z0-9]{9}\d\b"                      # ISIN shape
        r"|\b(?:[A-Z][\w&.\-]+\s+){1,4}"                   # Capitalised name run
        r"(?:Ltd|Limited|Inc|Corp|Corporation|PLC|AG|SA|NV|Co|Group|Holdings|Metals|Energy|Maintenance)\b",
    ),
    "currency":   re.compile(r"\b(USD|EUR|GBP|JPY|CHF|HKD|SGD|AUD|CNY|CNH|INR)\b"),
    "trade_date": re.compile(r"\b\d{1,2}[-/][A-Za-z]{3}[-/]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b"),
    "constraint": re.compile(r"\b(no\s+short|not?\s+exceed|do\s+not|must\s+not|ensure|please\s+ensure)\b", re.I),
}

# Phenomena tags, auto-suggested. Confirm or correct them by hand.
TAGS: dict[str, re.Pattern[str]] = {
    "quoted-thread":     re.compile(r"^\s*(From|Sent|To):\s|^\s*On .{5,60} wrote:|^\s*>", re.M),
    "bloomberg-ticker":  re.compile(r"\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"),
    "sell-all":          re.compile(r"\bsell\s+all\b", re.I),
    "boilerplate-heavy": re.compile(r"confidential|intended (solely )?for|Sent from my|Sent from \w+ Mail", re.I),
    "tabular":           re.compile(r"^.*\|.*\|.*$|^\s*(AC name|Trade date|Ticker|Security)\b", re.M),
    "constraint":        re.compile(r"\bno\s+short\s+selling\b", re.I),
}

ORDER_VERB = re.compile(r"\b(buy|sell|purchase|sold|bought|redeem|switch)\w*\b", re.I)


def body_of(msg) -> tuple[str, str]:
    """Return (text, which_part). Prefer plain; fall back to html."""
    if part := msg.get_body(("plain",)):
        return part.get_content(), "BODY_TEXT"
    if part := msg.get_body(("html",)):
        return part.get_content(), "BODY_HTML"
    return "", "BODY_TEXT"


def candidates(text: str, part: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for field, pattern in ANCHORS.items():
        hits = [
            {"start": m.start(), "end": m.end(), "excerpt": m.group(0).strip(), "part": part}
            for m in pattern.finditer(text)
        ]
        if hits:
            out[field] = hits[:12]   # more than twelve is noise, not help
    return out


def detect_tags(text: str, msg) -> list[str]:
    tags = [name for name, pattern in TAGS.items() if pattern.search(text)]

    if not ORDER_VERB.search(text):
        tags.append("negative-no-order")      # verify — this drives line recall

    if any(p.get_filename() for p in msg.walk()):
        tags.append("has-attachment")

    if any(unicodedata.category(c).startswith("Lo") for c in text):
        tags.append("non-english")            # ideographic characters present

    if len(ORDER_VERB.findall(text)) > 1:
        tags.append("possibly-multi-line")

    return sorted(set(tags))


def slug(subject: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (subject or fallback).lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s[:48] or fallback).rstrip("-")


def scaffold(src: Path, out_root: Path, index: int) -> Path:
    msg = BytesParser(policy=policy.default).parsebytes(src.read_bytes())
    text, part = body_of(msg)

    name = f"{index:04d}-{slug(str(msg['Subject'] or ''), src.stem)}"
    d = out_root / name
    d.mkdir(parents=True, exist_ok=True)

    (d / "source.eml").write_bytes(src.read_bytes())

    tags = detect_tags(text, msg)
    cands = candidates(text, part)

    label = {
        "_schema": "capture.v1",
        "_TODO": (
            "SCAFFOLD — not a label yet. Every field is UNRESOLVED with "
            "_candidates beside it. Promote what is real, delete the rest, "
            "then remove this key and every _candidates block."
        ),
        "envelope": {
            "sender_address": str(msg["From"] or ""),
            "language": "non-english" in tags and "TODO" or "en",
            "live_region": {
                "part": part, "start": 0, "end": len(text),
                "_TODO": "whole body assumed live — narrow this if quoted-thread is tagged",
            },
        },
        "lines": [
            {
                "line_index": 0,
                "side":        {"state": "UNRESOLVED"},
                "instrument":  {"raw_text": None, "form": None, "stated_currency": None,
                                "stated_venue": None, "resolved": None},
                "quantity":    {"kind": "UnresolvedQuantity", "raw_text": None},
                "execution":   {"order_type": {"state": "UNRESOLVED"},
                                "limit_price": None,
                                "strategy": {"state": "UNRESOLVED"},
                                "horizon": {"state": "UNRESOLVED"},
                                "expiry": {"state": "UNRESOLVED"}},
                "trade_date":  {"state": "UNRESOLVED"},
                "account_ref": {"state": "UNRESOLVED", "raw_text": None},
                "unmapped": [],
            }
        ],
        "unmapped": [],
        "_candidates": cands,
        "_body_preview": text[:600],
    }
    (d / "expected.capture.json").write_text(
        json.dumps(label, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    (d / "labels.yaml").write_text(
        "split: dev            # dev | holdout\n\n"
        "tags:                 # AUTO-SUGGESTED — confirm each one\n"
        + ("".join(f"  - {t}\n" for t in tags) or "  - TODO\n")
        + "\nlabelled_by: []       # two people, independently, for the first ten\n"
          "labelled_at:\ndisagreements:        # record these — they are your accuracy ceiling\n",
        encoding="utf-8")

    (d / "notes.md").write_text(
        f"# {name}\n\n"
        "## Why this fixture exists\n\nTODO\n\n"
        "## Judgement calls made here\n\nTODO — record every non-obvious decision.\n"
        "The next person labelling needs to make the same call the same way.\n\n"
        "## Provenance\n\nConverted from .msg: TODO yes/no\nRedacted: yes\n",
        encoding="utf-8")

    flag = "  <-- NEGATIVE?" if "negative-no-order" in tags else ""
    print(f"  {name}{flag}")
    print(f"      tags: {', '.join(tags) or 'none'}")
    print(f"      candidate spans: " +
          ", ".join(f"{k}×{len(v)}" for k, v in sorted(cands.items())))
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold fixture dirs from redacted .eml")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--start", type=int, default=1, help="first fixture number")
    args = ap.parse_args(argv)

    files: list[Path] = []
    for s in args.sources:
        p = Path(s)
        files.extend(sorted(p.rglob("*.eml")) if p.is_dir() else [p])
    if not files:
        print("no .eml files found", file=sys.stderr)
        return 1

    print(f"{len(files)} file(s) -> {args.out}\n")
    for i, f in enumerate(files, start=args.start):
        scaffold(f, args.out, i)

    print(f"""
Scaffolded. Now the part only a human can do:

  1. Open expected.capture.json. For each field, promote a candidate or
     leave it UNRESOLVED. Delete every _candidates block and the _TODO keys
     as you go — a leftover _TODO means the fixture is not finished.
  2. Confirm the auto-suggested tags. `negative-no-order` especially:
     a wrongly-tagged negative corrupts line recall.
  3. Write notes.md. The judgement calls are the point — without them the
     next fifty fixtures will be labelled differently from these ten.

Two people label the first ten independently, then compare. Disagreement is
usually the schema admitting two readings, not carelessness — and the rate
is your accuracy ceiling.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
