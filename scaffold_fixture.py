#!/usr/bin/env python3
"""Scaffold corpus fixture directories from redacted .eml files.

    python scripts/scaffold_fixture.py corpus/staging/*.eml -o corpus/fixtures/

RUN THIS ON REDACTED EMAIL, NOT ORIGINALS.
Provenance offsets are computed against the body text in source.eml. Scaffold
first and redact after, and every offset past the first replacement shifts.

WHAT THIS DOES AND DOES NOT DO

It finds *spans* — the mechanical part. Exact character offsets for plausible
anchors.

It does NOT decide *meaning*. Every field comes out UNRESOLVED with a
`_candidates` list beside it. You promote a candidate or delete it. If the
script guessed values and a tired labeller skimmed, the corpus would become
machine guesses wearing the authority of human labels, and every eval after
that would measure the model against a slightly worse version of itself.

It saves the typing. It must not save the thinking.

SCAN ZONES

Candidates are only collected from the message zone — the text before the
sign-off. Signature blocks and legal disclaimers are excluded, because they
are full of things that look exactly like order data and are not:

    instrument   <- "Meridian Capital Partners Pte Ltd"   (the sender's firm)
    quantity     <- "000001"                              (a postcode)
    quantity     <- "0003"                                (a phone number)

Those were real false positives from a real email. A wrong candidate is not
free: a plausible one anchors the labeller's judgement, which is precisely
what this script must not do.

Excluded zones are reported, never silently dropped.
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

# ------------------------------------------------------------------ zones ---

SIGNOFF_RE = re.compile(
    r"^[^\S\n]*(Best\s+regards|Kind\s+regards|Warm\s+regards|Regards|Sincerely"
    r"|Many\s+thanks|Thanks|Thks|Thank\s+you|Cheers|Best|Rgds|BR)\b[,.]?[^\S\n]*$",
    re.I | re.M,
)
DISCLAIMER_RE = re.compile(
    r"^[^\S\n]*(NOTICE:|DISCLAIMER|This\s+e-?mail\s+(is|may)|The\s+information\s+contained"
    r"|If\s+you\s+are\s+not\s+(one\s+of\s+)?the\s+intended)",
    re.I | re.M,
)


def message_zone(text: str) -> tuple[int, list[str]]:
    """Where the client's own words end. Returns (cut, what_was_excluded)."""
    cut, excluded = len(text), []

    if m := SIGNOFF_RE.search(text):
        cut, _ = m.start(), excluded.append("signature")
    if m := DISCLAIMER_RE.search(text):
        if m.start() < cut:
            cut = m.start()
            excluded = ["disclaimer"] if "signature" not in excluded else excluded + ["disclaimer"]
        elif "disclaimer" not in excluded:
            excluded.append("disclaimer")

    return cut, excluded


# ---------------------------------------------------------------- anchors ---

ANCHORS: dict[str, re.Pattern[str]] = {
    "side": re.compile(
        r"\b(buy|buying|bought|purchas\w+|sell|selling|sold|dispose\w*|redeem\w*|switch\w*)\b", re.I),

    # "all"/"entire" first — they are the interesting case. Bare numbers last.
    "quantity": re.compile(
        r"\b(all|entire\s+(?:position|holding|stake)?|whole\s+(?:position|holding)?|everything)\b"
        r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"        # 91,647  16,270,800
        r"|\b\d+\.\d+\b"                             # 440.16
        r"|\b\d{2,}\b",                              # 3900
        re.I),

    "order_type": re.compile(r"\b(at\s+market|market\s+order|mkt|@\s*market|limit|lmt|at\s+best)\b", re.I),
    "strategy":   re.compile(r"\b(vwap|twap|pov|at\s+close|at\s+open|iceberg|dark)\b", re.I),
    "horizon":    re.compile(
        r"\b(over\s+the\s+day|today|day\s+order|good\s+till\s+(?:date|cancel\w*)|gtc|gtd|fok|ioc)\b", re.I),

    "instrument": re.compile(
        r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"                            # ISIN
        r"|\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"               # Bloomberg ticker
        r"|\b(?:[A-Z][\w&.\-]*\s+){1,5}"                        # capitalised run, then...
        r"(?i:fund|funds|trust|etf|sicav|bond|notes|shares|metals|energy|maintenance"
        r"|ltd|limited|inc|corp|plc|holdings|group)\b"              # suffix, any case
        r"|\b(?:[A-Z][\w&.\-]*\s+){1,5}(?:AG|SA|NV|KK|SpA)\b"),   # these must stay upper

    "currency":   re.compile(r"\b(USD|EUR|GBP|JPY|CHF|HKD|SGD|AUD|CNY|CNH|INR)\b"),
    "trade_date": re.compile(
        r"\b\d{1,2}[-/.][A-Za-z]{3}[-/.]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b"),

    # Labelled forms, then bare account shapes — including space-separated
    # groups, which "order for 0000 00000001" showed we were missing.
    "account_ref": re.compile(
        r"\b(?:a/?c|acct|account|ac\s*(?:name|no)|portfolio|order\s+for)\b[\s.:#-]*"
        r"([A-Z0-9][\w\s-]{3,24}?)(?=[?.,;\n]|$)"
        r"|\b\d{3}-\d{5}-\d{2}\b"
        r"|\b\d{4}\s+\d{6,10}\b"
        r"|\b[A-Z]{2}\d{8,12}\b",
        re.I),

    "constraint": re.compile(
        r"\b(no\s+short|not?\s+exceed|do\s+not|must\s+not|please\s+ensure|ensure\s+that)\b", re.I),
}

TAGS: dict[str, re.Pattern[str]] = {
    "quoted-thread":     re.compile(r"^\s*(From|Sent|To):\s|^\s*On .{5,60} wrote:|^\s*>", re.M),
    "bloomberg-ticker":  re.compile(r"\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"),
    "isin-stated":       re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"),
    "sell-all":          re.compile(r"\b(sell\s+all|entire\s+position|sell\s+the\s+whole)\b", re.I),
    "fund-order":        re.compile(r"\b(fund|redemption|subscri\w+|nav)\b", re.I),
    "boilerplate-heavy": re.compile(r"confidential|intended (solely )?for|Sent from my|Sent from \w+ Mail", re.I),
    "tabular":           re.compile(r"^.*\|.*\|.*$|^\s*(AC name|Trade date|Ticker|Security)\b", re.M),
    "constraint":        re.compile(r"\bno\s+short\s+selling\b", re.I),
}

# Inflections matter here: \bsell\b does not match "selling", and a missed
# verb tags a real order as negative-no-order — which corrupts line recall,
# a hard gate. Suffix every stem.
ORDER_VERB = re.compile(
    r"\b(buy\w*|sell\w*|sold|purchas\w*|bought|redeem\w*|switch\w*|dispos\w*|liquidat\w*)\b", re.I)


def body_of(msg) -> tuple[str, str]:
    if part := msg.get_body(("plain",)):
        return part.get_content(), "BODY_TEXT"
    if part := msg.get_body(("html",)):
        return part.get_content(), "BODY_HTML"
    return "", "BODY_TEXT"


def candidates(text: str, part: str, cut: int) -> dict[str, list[dict]]:
    """Collect anchors from the message zone only — text[:cut]."""
    zone = text[:cut]
    out: dict[str, list[dict]] = {}
    for field, pattern in ANCHORS.items():
        hits = [
            {"start": m.start(), "end": m.end(), "excerpt": m.group(0).strip(), "part": part}
            for m in pattern.finditer(zone)
        ]
        if hits:
            out[field] = hits

    # The digits inside "order for 0000 00000001" are not a quantity, and the
    # numbers inside an instrument name are not either. A more specific match
    # claims its span.
    claimed = [(h["start"], h["end"]) for f in ("account_ref", "instrument")
               for h in out.get(f, [])]
    for field in ("quantity", "currency", "trade_date"):
        if field in out:
            out[field] = [
                h for h in out[field]
                if not any(s <= h["start"] and h["end"] <= e for s, e in claimed)
            ]
            if not out[field]:
                del out[field]

    return {f: h[:12] for f, h in out.items()}


def inline_images(msg) -> list[str]:
    return [
        p.get_filename() or p.get_content_type()
        for p in msg.walk()
        if p.get_content_maintype() == "image"
    ]


def detect_tags(text: str, msg, images: list[str]) -> list[str]:
    tags = [name for name, pattern in TAGS.items() if pattern.search(text)]
    if not ORDER_VERB.search(text):
        tags.append("negative-no-order")
    if images:
        tags.append("embedded-image")
    if any(p.get_filename() and p.get_content_maintype() != "image" for p in msg.walk()):
        tags.append("has-attachment")
    if any(unicodedata.category(c).startswith("Lo") for c in text):
        tags.append("non-english")
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
    cut, excluded = message_zone(text)
    images = inline_images(msg)
    tags = detect_tags(text, msg, images)
    cands = candidates(text, part, cut)

    name = f"{index:04d}-{slug(str(msg['Subject'] or ''), src.stem)}"
    d = out_root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.eml").write_bytes(src.read_bytes())

    # A short message zone plus images means the order is probably IN the
    # image, where no regex will ever reach it.
    image_heavy = bool(images) and len(text[:cut].strip()) < 400

    label = {
        "_schema": "capture.v1",
        "_TODO": (
            "SCAFFOLD — not a label yet. Promote real candidates, delete the "
            "rest, then remove this key and every _candidates block."
        ),
        "envelope": {
            "sender_address": str(msg["From"] or ""),
            "language": "TODO" if "non-english" in tags else "en",
            "live_region": {
                "part": part, "start": 0, "end": cut,
                "_TODO": f"message zone; excluded: {', '.join(excluded) or 'nothing'}",
            },
        },
        "lines": [{
            "line_index": 0,
            "side":        {"state": "UNRESOLVED"},
            "instrument":  {"raw_text": None, "form": None, "stated_currency": None,
                            "stated_venue": None, "resolved": None},
            "quantity":    {"kind": "UnresolvedQuantity", "raw_text": None},
            "execution":   {"order_type": {"state": "UNRESOLVED"}, "limit_price": None,
                            "strategy": {"state": "UNRESOLVED"},
                            "horizon": {"state": "UNRESOLVED"},
                            "expiry": {"state": "UNRESOLVED"}},
            "trade_date":  {"state": "UNRESOLVED"},
            "account_ref": {"state": "UNRESOLVED", "raw_text": None},
            "unmapped": [],
        }],
        "unmapped": [],
        "_candidates": cands,
        "_scan": {
            "message_zone": [0, cut],
            "excluded": excluded,
            "inline_images": images,
            "image_heavy": image_heavy,
        },
        "_body_preview": text[:cut][:600],
    }
    (d / "expected.capture.json").write_text(
        json.dumps(label, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    warn = ""
    if image_heavy:
        warn = ("\n# NOTE: little body text and an embedded image — the order is\n"
                "# probably IN the image. Label this one by eye; the candidates\n"
                "# below are necessarily thin. Tag: embedded-image.\n")

    (d / "labels.yaml").write_text(
        "split: dev            # dev | holdout\n" + warn +
        "\ntags:                 # AUTO-SUGGESTED — confirm each one\n"
        + ("".join(f"  - {t}\n" for t in tags) or "  - TODO\n")
        + "\nlabelled_by: []\nlabelled_at:\ndisagreements:\n",
        encoding="utf-8")

    (d / "notes.md").write_text(
        f"# {name}\n\n## Why this fixture exists\n\nTODO\n\n"
        "## Judgement calls made here\n\nTODO — record every non-obvious decision.\n\n"
        "## Provenance\n\nConverted from .msg: TODO\nRedacted: yes\n"
        + (f"\n## Warning\n\nOrder content appears to be inside an embedded image "
           f"({len(images)} image part(s)). Text candidates are thin by nature.\n"
           if image_heavy else ""),
        encoding="utf-8")

    flag = ""
    if image_heavy:
        flag = "   <-- IMAGE-HEAVY: label by eye"
    elif "negative-no-order" in tags:
        flag = "   <-- NEGATIVE?"

    print(f"  {name}{flag}")
    print(f"      tags: {', '.join(tags) or 'none'}")
    if excluded:
        print(f"      excluded from scan: {', '.join(excluded)} (from char {cut})")
    print(f"      candidates: " + (", ".join(f"{k}x{len(v)}" for k, v in sorted(cands.items())) or "none"))
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold fixture dirs from redacted .eml")
    ap.add_argument("sources", nargs="+")
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--start", type=int, default=1)
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

    print("""
Now the part only a human can do:

  1. Promote or delete every candidate. Remove each _candidates block and
     _TODO key as you finish — a leftover _TODO means unfinished, which is
     easy to grep for before committing.
  2. Confirm the tags. `negative-no-order` especially: a wrongly-tagged
     negative corrupts line recall, which is a hard gate.
  3. Check `_scan.excluded`. Signature and disclaimer text is not scanned —
     if a real instruction lives down there, add it by hand.
  4. Write notes.md. The judgement calls are the point.

Anything marked IMAGE-HEAVY needs reading by eye. No amount of regex reaches
into a screenshot.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
