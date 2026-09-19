#!/usr/bin/env python3
"""Scaffold one `label.yaml` per redacted .eml, for a human to fill in.

    python scripts/scaffold_fixture.py corpus/staging/*.eml -o corpus/fixtures/
    $EDITOR corpus/fixtures/0001-*/label.yaml
    python scripts/build_fixture.py corpus/fixtures/0001-*

Each fixture directory gets exactly two files:

    source.eml    the redacted original
    label.yaml    THE ONLY FILE A HUMAN EDITS

`expected.capture.json` is generated from `label.yaml` by build_fixture.py,
which derives every character offset by locating the value you wrote in the
body text. You never type an offset and you are never asked to check one,
because nobody can check one by eye.

WHAT THIS DOES AND DOES NOT DO

For a **table** — a column header plus data rows — it reads the columns and
fills the cells in verbatim. That is transcription, not guessing, so the
values are pre-filled and you are correcting rather than typing.

For **prose** it can only pattern-match, so it pre-fills a field only when
exactly one candidate was found. Where several were found the field is left
blank with the options listed in a comment beside it. A plausible wrong value
anchors a labeller's judgement, which is the one thing this script must not do.

It saves the typing. It must not save the thinking.

The message zone — the client's own words, before the sign-off — is appended
to label.yaml as a comment block, so you can read the email and label it in
one window.
"""

from __future__ import annotations

import argparse
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


# --------------------------------------------------------- table reading ----

# Column header synonyms. Longest first within each field so "value date" wins
# over "date", and "a/c no" over "no".
COLUMN_MAP: list[tuple[str, re.Pattern[str]]] = [
    ("trade_date", re.compile(r"\b(trade\s*date|value\s*date|settle\w*\s*date|date)\b", re.I)),
    ("side",       re.compile(r"\b(orders?|side|b\s*/\s*s|buy\s*/\s*sell|action|transaction)\b", re.I)),
    ("ticker",     re.compile(r"\b(ticker|bloomberg|bbg|code|symbol)\b", re.I)),
    ("isin",       re.compile(r"\b(isin|sedol|cusip)\b", re.I)),
    ("instrument", re.compile(r"\b(securit(?:y|ies)|instrument|stock|fund|name|description)\b", re.I)),
    ("currency",   re.compile(r"\b(ccy|currency|curr)\b", re.I)),
    ("quantity",   re.compile(r"\b(qty|quantity|units|shares|nominal|amount|size)\b", re.I)),
    ("price",      re.compile(r"\b(price|limit|lmt|px)\b", re.I)),
    ("account",    re.compile(r"\b(ac\s*name|account|a\s*/\s*c\s*no?|portfolio|client)\b", re.I)),
    ("venue",      re.compile(r"\b(market|exchange|venue)\b", re.I)),
]

CELL_SPLIT = re.compile(r"\t+|\s*\|\s*|\s{2,}")
ROW_SIDE = re.compile(r"\b(buy|bot|bought|sell|sld|sold|purchase|redeem|redemption|switch|subscribe)\b", re.I)
HAS_DIGIT = re.compile(r"\d")


def cells(line: str) -> list[str]:
    return [c.strip() for c in CELL_SPLIT.split(line.strip()) if c.strip()]


def read_header(line: str) -> list[str | None] | None:
    """Map each header cell to a field name. None for a column we don't use."""
    cs = cells(line)
    if len(cs) < 3:
        return None
    mapped: list[str | None] = []
    for c in cs:
        for field, pattern in COLUMN_MAP:
            if pattern.search(c) and field not in mapped:
                mapped.append(field)
                break
        else:
            mapped.append(None)
    # Two real columns is a coincidence; three is a table.
    return mapped if sum(1 for m in mapped if m) >= 3 else None


def read_table(zone: str) -> tuple[list[dict], list[str | None], list[str]] | None:
    """Find a header row and read the data rows beneath it into field dicts."""
    lines = zone.split("\n")
    for i, line in enumerate(lines):
        header = read_header(line)
        if not header:
            continue

        rows, notes, ragged = [], [], 0
        for raw in lines[i + 1:]:
            if not raw.strip():
                continue
            cs = cells(raw)
            if len(cs) < 3 or not (ROW_SIDE.search(raw) or HAS_DIGIT.search(raw)):
                continue
            if len(cs) != len(header):
                ragged += 1
                notes.append(f"{len(cs)} cells against {len(header)} columns: {raw.strip()[:70]!r}")
            rows.append({f: v for f, v in zip(header, cs) if f})

        if len(rows) >= 2:
            if ragged:
                notes.insert(0, f"{ragged} of {len(rows)} rows did not line up with the header "
                                "— check those rows cell by cell")
            notes.insert(0, f"header: {line.strip()[:80]!r}")
            return rows, header, notes
    return None


# ------------------------------------------------- prose pattern matching ---

ANCHORS: dict[str, re.Pattern[str]] = {
    "side": re.compile(
        r"\b(buy|buying|bought|purchas\w+|sell|selling|sold|dispose\w*|redeem\w*|switch\w*)\b", re.I),

    "ticker": re.compile(r"\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"),
    "isin":   re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"),

    # A capitalised run then a suffix. Separator is one or two plain spaces,
    # never a tab or a run of them — in a flattened table those ARE the column
    # boundaries, and `\s+` happily produced "Jul-26\tBUY\tSIEMENS ENERGY".
    "instrument": re.compile(
        r"\b(?:[A-Z][\w&.\-]*[ ]{1,2}){1,5}"
        r"(?i:fund|funds|trust|etf|sicav|bond|notes|shares|metals|energy|maintenance"
        r"|ltd|limited|inc|corp|plc|holdings|group)\b"
        r"|\b(?:[A-Z][\w&.\-]*[ ]{1,2}){1,5}(?:AG|SA|NV|KK|SpA)\b"),

    # "all"/"entire" first — they are the interesting case. Bare numbers last.
    "quantity": re.compile(
        r"\b(all|entire\s+(?:position|holding|stake)?|whole\s+(?:position|holding)?|everything)\b"
        r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"
        r"|\b\d+\.\d+\b"
        r"|\b\d{2,}\b",
        re.I),

    "currency":   re.compile(r"\b(USD|EUR|GBP|JPY|CHF|HKD|SGD|AUD|CNY|CNH|INR)\b"),
    "order_type": re.compile(r"\b(at\s+market|market\s+order|mkt|@\s*market|limit|lmt|at\s+best)\b", re.I),
    "strategy":   re.compile(r"\b(vwap|twap|pov|at\s+close|at\s+open|iceberg|dark)\b", re.I),
    "horizon":    re.compile(
        r"\b(over\s+the\s+day|today|day\s+order|good\s+till\s+(?:date|cancel\w*)|gtc|gtd|fok|ioc)\b", re.I),
    "trade_date": re.compile(
        r"\b\d{1,2}[-/.][A-Za-z]{3}[-/.]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b"),

    "account": re.compile(
        r"\b(?:a/?c|acct|account|ac\s*(?:name|no)|portfolio|order\s+for)\b[\s.:#-]*"
        r"([A-Z0-9][\w\s-]{3,24}?)(?=[?.,;\n]|\s{2,}|$)"
        r"|\b\d{3}-\d{4,8}-\d{2,3}\b"
        r"|\b\d{4}\s+\d{6,10}\b"
        r"|\b[A-Z]{2}\d{8,12}\b",
        re.I),
}

# Digits that are never a quantity. Matched to be excluded, never offered.
NOISE = re.compile(
    r"\b(?:tel|phone|mobile|mob|fax|dir(?:ect)?|voicelog)\b[^\n]{0,40}"
    r"|\+\d[\d\s()\-]{6,}",
    re.I)

CONSTRAINT = re.compile(
    r"[^\n.]*\b(no\s+short\s+sell\w*|do\s+not\s+\w+|must\s+not\s+\w+|not?\s+exceed)\b[^\n.]*", re.I)

ORDER_VERB = re.compile(
    r"\b(buy\w*|sell\w*|sold|purchas\w*|bought|redeem\w*|switch\w*|dispos\w*|liquidat\w*)\b", re.I)

PROSE_BREAK = re.compile(r"\n|;|\.\s|\band\s+(?:also\s+)?|\bthen\b|\balso\b", re.I)


def prose_spans(zone: str) -> list[tuple[int, int]]:
    """One span per apparent order, or a single span covering everything."""
    verbs = list(ORDER_VERB.finditer(zone))
    if len(verbs) < 2:
        return [(0, len(zone))]

    cuts = [0]
    for a, b in zip(verbs, verbs[1:]):
        breaks = [m.start() for m in PROSE_BREAK.finditer(zone, a.end(), b.start())]
        cuts.append(breaks[-1] if breaks else (a.end() + b.start()) // 2)
    cuts.append(len(zone))
    return [(s, e) for s, e in zip(cuts, cuts[1:]) if zone[s:e].strip()]


def match_fields(zone: str, lo: int, hi: int) -> dict[str, list[str]]:
    """Candidate value strings per field inside zone[lo:hi]."""
    found: dict[str, list[tuple[int, int, str]]] = {}
    for field, pattern in ANCHORS.items():
        hits = [(m.start(), m.end(), m.group(0).strip()) for m in pattern.finditer(zone, lo, hi)]
        if hits:
            found[field] = hits

    claimed = [(s, e) for f in ("account", "instrument", "ticker", "isin", "trade_date")
               for s, e, _ in found.get(f, [])]
    claimed += [(m.start(), m.end()) for m in NOISE.finditer(zone, lo, hi)]
    if "quantity" in found:
        found["quantity"] = [h for h in found["quantity"]
                             if not any(s <= h[0] and h[1] <= e for s, e in claimed)]

    out = {}
    for field, hits in found.items():
        seen, vals = set(), []
        for _, _, v in hits:
            if v.lower() not in seen:
                seen.add(v.lower())
                vals.append(v)
        if vals:
            out[field] = vals[:6]
    return out


# ------------------------------------------------------------------- tags ---

TAG_HINTS: dict[str, re.Pattern[str]] = {
    "quoted-thread":    re.compile(r"^\s*(From|Sent|To):\s|^\s*On .{5,60} wrote:|^\s*>", re.M),
    "bloomberg-ticker": re.compile(r"\b[A-Z0-9]{1,6}\s+[A-Z]{2}\s+EQUITY\b"),
    "isin-stated":      re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}\d\b"),
    "sell-all":         re.compile(r"\b(sell\s+all|entire\s+position|sell\s+the\s+whole)\b", re.I),
    "fund-order":       re.compile(r"\b(fund|redemption|subscri\w+|nav)\b", re.I),
    "constraint":       re.compile(r"\bno\s+short\s+sell\w*\b", re.I),
    "voicelog":         re.compile(r"\bvoice\s*log|\bcall\s+back\b|\bplease\s+call\b", re.I),
    "limit-order":      re.compile(r"\b(limit|lmt)\b", re.I),
    "strategy-stated":  re.compile(r"\b(vwap|twap|pov|at\s+close|at\s+open)\b", re.I),
}


def suggest_tags(text: str, msg, images: list[str], n_orders: int, tabular: bool) -> list[str]:
    tags = [t for t, p in TAG_HINTS.items() if p.search(text)]
    if tabular:
        tags.append("tabular")
    if n_orders > 1:
        tags.append("multi-line")
    if not ORDER_VERB.search(text):
        tags.append("negative-no-order")
    if images:
        tags.append("embedded-image")
    if any(p.get_filename() and p.get_content_maintype() != "image" for p in msg.walk()):
        tags.append("has-attachment")
    if any(p.get_filename() or "" for p in msg.walk() if (p.get_filename() or "").lower().endswith(".pdf")):
        tags.append("pdf-attachment")
    if any(unicodedata.category(c).startswith("Lo") for c in text):
        tags.append("non-english")
    return sorted(set(tags))


# ------------------------------------------------------------ yaml writing ---

FIELDS = ["side", "instrument", "ticker", "isin", "quantity", "quantity_asserted",
          "currency", "order_type", "limit_price", "strategy", "horizon",
          "trade_date", "account"]

# Only `quantity: all` uses it, so a blank line for it on every order is noise.
FIELD_NOTES = {
    "quantity_asserted": 'only with `quantity: all` — the figure in "sell all (91,647)"',
}

NEEDS_QUOTES = re.compile(r"^[\s>|*&!%@`#-]|[:#]\s|['\"]|^$")


def scalar(v: str | None) -> str:
    if v is None or v == "":
        return ""
    v = str(v).strip()
    return f'"{v}"' if NEEDS_QUOTES.search(v) else v


def order_block(values: dict[str, str], hints: dict[str, list[str]], comment: str,
                verbose: bool = True) -> str:
    """One `- side: ...` block. Blank field + `# ?` comment where we guessed.

    `verbose` is set only on the first block: the explanatory comments are
    worth one screen of reading, not fourteen repetitions of it.
    """
    out = [f"  # {comment}\n"] if comment else []
    first = True
    for f in FIELDS:
        v = values.get(f) or ""
        note = ""
        if not v and len(hints.get(f, [])) > 1:
            note = "   # ? " + " | ".join(hints[f][:4])
        elif not v and f in ("side", "instrument", "quantity"):
            note = "   # <- required if this is a real order"
        elif not v and f in FIELD_NOTES and verbose:
            note = f"   # {FIELD_NOTES[f]}"
        lead = "  - " if first else "    "
        out.append(f"{lead}{f+':':<13}{scalar(v)}{note}".rstrip() + "\n")
        first = False
    out.append("    unmapped: []" +
               ("          # client said something the schema can't hold" if verbose else "") + "\n")
    return "".join(out)


def write_label(d: Path, name: str, split: str, tags: list[str], account: str,
                constraints: list[str], orders: list[str], zone: str,
                how: str, notes: list[str], excluded: list[str]) -> None:
    body = [
        f"# {name}\n#\n",
        f"# {len(orders)} order(s) found by {how}.\n#\n",
        "# EDIT THIS FILE. NOTHING ELSE. Then:\n",
        f"#     python scripts/build_fixture.py corpus/fixtures/{name}\n#\n",
        "# 1. COUNT THE ORDERS FIRST. Add or delete `orders:` entries until there\n",
        "#    is exactly one per order the client gave. Line recall is a hard 100%\n",
        "#    gate, so a missing entry lowers the bar instead of failing loudly.\n",
        "# 2. Copy values from the email VERBATIM. build_fixture.py finds each one\n",
        "#    in the body to derive its offsets — a paraphrase will not be found.\n",
        "# 3. Leave a field blank if the client did not state it. Blank is a real\n",
        "#    answer (Unresolved), not an omission.\n",
        "# 4. Tags must come from corpus/schema/tags.yaml.\n",
    ]
    for n in notes:
        body.append(f"#\n# NOTE: {n}\n")
    if excluded:
        body.append(f"#\n# Not scanned: {', '.join(excluded)}. If a real instruction lives\n"
                    "# down there, add it by hand.\n")

    body.append(f"\nsplit: {split}                 # dev | holdout\n")
    body.append("language: en               # ISO code of the body\n")
    body.append("\ntags:\n")
    body.extend(f"  - {t}\n" for t in tags)
    if not tags:
        body.append("  -                     # see corpus/schema/tags.yaml\n")

    body.append("\n# Applies to every order below unless an order sets its own.\n"
                + f"account: {scalar(account)}".rstrip() + "\n")
    body.append("\nconstraints:\n")
    body.extend(f"  - {scalar(c)}\n" for c in constraints)

    body.append("\norders:\n\n")
    body.append("\n".join(orders) if orders else "  []\n")

    body.append("\nnotes: |\n  Why this fixture exists, and every judgement call made labelling it.\n"
                "  TODO\n")
    body.append("\nlabelled_by: []\ndisagreements: []\n")
    body.append("\n# ---------------------------------------------------------------------\n"
                "# The client's own words, for reference. Do not edit.\n#\n")
    body.extend(f"#   {ln}\n" for ln in zone.strip().split("\n"))

    (d / "label.yaml").write_text("".join(body), encoding="utf-8")


# --------------------------------------------------------------- scaffold ---

def body_of(msg) -> tuple[str, str]:
    if part := msg.get_body(("plain",)):
        return part.get_content(), "BODY_TEXT"
    if part := msg.get_body(("html",)):
        return part.get_content(), "BODY_HTML"
    return "", "BODY_TEXT"


def slug(subject: str, fallback: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (subject or fallback).lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return (s[:48] or fallback).rstrip("-")


def scaffold(src: Path, out_root: Path, index: int) -> Path:
    msg = BytesParser(policy=policy.default).parsebytes(src.read_bytes())
    text, part = body_of(msg)
    cut, excluded = message_zone(text)
    zone = text[:cut]
    images = [p.get_filename() or p.get_content_type() for p in msg.walk()
              if p.get_content_maintype() == "image"]

    notes: list[str] = []
    accounts: list[str] = []
    blocks: list[str] = []

    if table := read_table(zone):
        rows, _, tnotes = table
        notes += tnotes
        how, tabular = "reading the table columns", True
        for i, row in enumerate(rows, 1):
            values = {f: row.get(f, "") for f in FIELDS}
            if price := row.get("price", ""):
                if re.fullmatch(r"(?i)mkt|market|at\s+market|best", price):
                    values["order_type"] = price
                elif re.fullmatch(r"[\d.,]+", price):
                    values["order_type"], values["limit_price"] = "LIMIT", price
                else:
                    notes.append(f"row {i}: price cell {price!r} is neither MKT nor a number")
            if a := row.get("account"):
                accounts.append(a)
                values["account"] = a
            blocks.append(order_block(values, {}, f"row {i}", verbose=(i == 1)))
    else:
        spans = prose_spans(zone)
        how = "pattern-matching prose" + (f", split into {len(spans)}" if len(spans) > 1 else "")
        tabular = False
        if len(spans) > 1:
            notes.append(f"{len(spans)} order verbs in prose — this split is a guess. "
                         "Re-read the body below and fix the count before labelling fields.")
        for i, (lo, hi) in enumerate(spans, 1):
            hints = match_fields(zone, lo, hi)
            values = {f: (v[0] if len(v) == 1 else "") for f, v in hints.items()}
            if len(spans) > 1:
                excerpt = " ".join(zone[lo:hi].split())[:60]
                blocks.append(order_block(values, hints, f"order {i}: {excerpt}", verbose=(i == 1)))
            else:
                blocks.append(order_block(values, hints, ""))

    # An account stated once for the whole email is hoisted, so it is written
    # once rather than copied onto fourteen rows.
    whole = match_fields(zone, 0, len(zone))
    account = ""
    if accounts and len(set(accounts)) == 1:
        account = accounts[0]
        for i, b in enumerate(blocks):
            blocks[i] = re.sub(rf"^(    account:\s+){re.escape(account)}\s*$",
                               r"\1", b, flags=re.M)
    elif len(whole.get("account", [])) == 1:
        account = whole["account"][0]
    elif len(whole.get("account", [])) > 1:
        notes.append("several account references: " + " | ".join(whole["account"][:4]))

    constraints = [" ".join(m.group(0).split()) for m in CONSTRAINT.finditer(zone)][:4]
    tags = suggest_tags(text, msg, images, len(blocks), tabular)

    if images and len(zone.strip()) < 400:
        notes.append("little body text and an embedded image — the order is probably IN "
                     "the image. Label this one by eye; nothing below is pre-filled.")

    name = f"{index:04d}-{slug(str(msg['Subject'] or ''), src.stem)}"
    d = out_root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "source.eml").write_bytes(src.read_bytes())
    write_label(d, name, "dev", tags, account, constraints, blocks, zone, how, notes, excluded)

    print(f"  {name}")
    print(f"      {len(blocks)} order(s) — {how}")
    for n in notes:
        print(f"      ! {n}")
    print(f"      tags: {', '.join(tags) or 'none'}")
    return d


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scaffold label.yaml from redacted .eml")
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
Next, per fixture:

  1. Open label.yaml. Check the order count. Fix the values.
  2. python scripts/build_fixture.py <fixture dir>

build_fixture.py derives the offsets and writes expected.capture.json. If it
cannot find a value you wrote, or finds it in more than one place it cannot
disambiguate, it says so and writes nothing.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
