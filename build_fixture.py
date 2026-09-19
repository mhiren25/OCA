#!/usr/bin/env python3
"""Compile a hand-written `label.yaml` into `expected.capture.json`.

    python scripts/build_fixture.py corpus/fixtures/0001-fw-order
    python scripts/build_fixture.py corpus/fixtures/          # all of them
    python scripts/build_fixture.py corpus/fixtures/ --check  # verify, write nothing

WHY THIS EXISTS

A capture label carries character offsets, because a reviewer looking at a
draft order needs to see which words in the email produced each value. But a
human cannot verify an offset by eye, so asking one to check them is theatre —
they will be nodded through, and a corpus with unverified provenance is worse
than one with none, because the eval reports a number nobody has grounds to
trust.

So the human writes values and only values. This derives the offsets by
finding each value in the body text. That inverts the burden correctly: the
person supplies meaning, the machine supplies coordinates, and each does the
part it can actually be held to.

It follows that **a value must be copied from the email verbatim**. A
paraphrase is not found, and not-found is an error, not a warning. That
constraint is a feature: it makes a label that drifts from its source
impossible to commit rather than merely discouraged.

HOW A VALUE IS PLACED

Values repeat — `MKT` appears on all fourteen rows. So each order is anchored
on its most distinctive value (a ticker, an ISIN, an instrument name) and the
order's other fields are matched to the occurrence nearest that anchor.
Anchors advance through the document, so two rows for the same instrument
still land on different rows.

Where that cannot be done unambiguously, this refuses to write and says which
value in which order it could not place. Silence would produce a fixture whose
offsets point at the wrong row, which no test would ever catch.
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

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from scaffold_fixture import message_zone  # noqa: E402  (shared zone logic)

SCHEMA = "capture.v1"

SIDE = {
    "BUY": "BUY", "B": "BUY", "BOT": "BUY", "BOUGHT": "BUY", "PURCHASE": "BUY", "BUYING": "BUY",
    "SELL": "SELL", "S": "SELL", "SLD": "SELL", "SOLD": "SELL", "SELLING": "SELL",
    "REDEEM": "REDEEM", "REDEMPTION": "REDEEM",
    "SUBSCRIBE": "SUBSCRIBE", "SUBSCRIPTION": "SUBSCRIBE",
    "SWITCH": "SWITCH",
}
ORDER_TYPE = {
    "MKT": "MARKET", "MARKET": "MARKET", "AT MARKET": "MARKET", "MARKET ORDER": "MARKET",
    "BEST": "MARKET", "AT BEST": "MARKET",
    "LIMIT": "LIMIT", "LMT": "LIMIT",
}
ENTIRE = re.compile(r"^(all|entire(\s+(position|holding|stake))?|whole(\s+(position|holding))?|everything)$", re.I)

# Fields whose value is a controlled token rather than free text, so a value
# outside the set is a labelling error and not a client phrasing to preserve.
CONTROLLED = {"side": SIDE, "order_type": ORDER_TYPE}


class LabelError(Exception):
    pass


# ------------------------------------------------------------- locating -----

def occurrences(hay: str, needle: str) -> tuple[list[tuple[int, int]], str]:
    """Every place `needle` appears in `hay`, and how it had to be matched."""
    needle = needle.strip()
    if not needle:
        return [], "empty"

    exact = [(m.start(), m.end()) for m in re.finditer(re.escape(needle), hay)]
    if exact:
        return exact, "exact"

    # A label typed with different spacing than the body is still the same
    # value; a label with different WORDS is not, so only whitespace flexes.
    loose = r"\s+".join(re.escape(t) for t in needle.split())
    if hits := [(m.start(), m.end()) for m in re.finditer(loose, hay)]:
        return hits, "whitespace"

    if hits := [(m.start(), m.end()) for m in re.finditer(loose, hay, re.I)]:
        return hits, "case-insensitive"

    return [], "not-found"


def place(hay: str, needle: str, anchor: int | None, where: str) -> dict:
    """Resolve one value to a span, nearest the anchor when it repeats."""
    hits, how = occurrences(hay, needle)
    if not hits:
        raise LabelError(
            f"{where}: {needle!r} does not appear in the email body. "
            "Copy the value verbatim from the text at the bottom of label.yaml, "
            "or clear the field if the client never said it.")

    if len(hits) > 1 and anchor is None:
        spots = ", ".join(str(s) for s, _ in hits[:6])
        raise LabelError(
            f"{where}: {needle!r} appears {len(hits)} times (at {spots}) and this "
            "order has no value distinctive enough to anchor it. Add something "
            "unique to this order — a ticker, an ISIN, the full instrument name.")

    start, end = min(hits, key=lambda h: abs(h[0] - anchor)) if anchor is not None else hits[0]
    return {"start": start, "end": end, "text": hay[start:end], "matched": how}


def anchor_for(hay: str, order: dict, after: int, where: str) -> int | None:
    """Pick the order's most distinctive value and return its position.

    Preference is deliberate: an identifier first, then a long name, then
    whatever else is unique. Quantity is last and price never — `MKT` and `290`
    are the values most likely to collide across rows.
    """
    ranked = sorted(
        ((f, str(v).strip()) for f, v in order.items()
         if f in ("isin", "ticker", "instrument", "account", "trade_date", "quantity")
         and v not in (None, "")),
        key=lambda kv: (("isin", "ticker", "instrument", "account",
                         "trade_date", "quantity").index(kv[0]), -len(kv[1])))

    for _, value in ranked:
        hits, _ = occurrences(hay, value)
        forward = [h for h in hits if h[0] >= after]
        if len(forward) == 1:
            return forward[0][0]
    # Nothing unique ahead of the previous order: take the first value's first
    # forward hit so fields at least cluster on the right row, and let the
    # caller's per-field placement raise if that turns out ambiguous.
    for _, value in ranked:
        hits, _ = occurrences(hay, value)
        if forward := [h for h in hits if h[0] >= after]:
            return forward[0][0]
    return None


# --------------------------------------------------------------- building ---

def tri(hay: str, value, anchor: int | None, where: str, field: str) -> dict:
    """Mapped with provenance, or Unresolved. Never a bare Optional."""
    if value in (None, ""):
        return {"state": "UNRESOLVED"}
    raw = str(value).strip()
    prov = place(hay, raw, anchor, f"{where}.{field}")
    out = {"state": "MAPPED", "raw_text": prov["text"], "provenance": prov}
    if table := CONTROLLED.get(field):
        key = re.sub(r"\s+", " ", raw).upper()
        if key not in table:
            raise LabelError(
                f"{where}.{field}: {raw!r} is not a recognised value. "
                f"Allowed: {', '.join(sorted(set(table.values())))} "
                f"(written as any of {', '.join(sorted(table))}).")
        out["value"] = table[key]
    else:
        out["value"] = raw
    return out


def quantity_of(hay: str, order: dict, anchor: int | None, where: str) -> dict:
    q = str(order.get("quantity") or "").strip()
    asserted = str(order.get("quantity_asserted") or "").strip()

    if not q:
        if asserted:
            raise LabelError(f"{where}.quantity_asserted is set but quantity is blank — "
                             "write `quantity: all` if the client said all.")
        return {"kind": "UnresolvedQuantity"}

    prov = place(hay, q, anchor, f"{where}.quantity")

    if ENTIRE.match(q):
        out = {"kind": "EntirePosition", "raw_text": prov["text"], "provenance": prov,
               "client_asserted": None, "resolved_position": None}
        if asserted:
            ap = place(hay, asserted, anchor, f"{where}.quantity_asserted")
            out["client_asserted"] = to_number(asserted, f"{where}.quantity_asserted")
            out["client_asserted_provenance"] = ap
        return out

    if asserted:
        raise LabelError(f"{where}.quantity_asserted only applies when quantity is "
                         f'"all" or similar, not to {q!r}.')
    return {"kind": "Absolute", "value": to_number(q, f"{where}.quantity"),
            "raw_text": prov["text"], "provenance": prov}


def to_number(raw: str, where: str) -> float | int:
    cleaned = raw.replace(",", "").replace(" ", "")
    try:
        return int(cleaned) if re.fullmatch(r"-?\d+", cleaned) else float(cleaned)
    except ValueError as exc:
        raise LabelError(f"{where}: {raw!r} is not a number.") from exc


def instrument_of(hay: str, order: dict, anchor: int | None, where: str) -> dict:
    name = str(order.get("instrument") or "").strip()
    ticker = str(order.get("ticker") or "").strip()
    isin = str(order.get("isin") or "").strip()

    if not (name or ticker or isin):
        return {"state": "UNRESOLVED", "raw_text": None, "form": None,
                "stated_currency": None, "stated_venue": None, "resolved": None}

    # The most specific identifier the client gave is what the enrichment
    # chain should key on, so record which form we have rather than flattening.
    form = "ISIN" if isin else ("TICKER" if ticker else "NAME")
    primary = isin or ticker or name
    out = {
        "state": "MAPPED",
        "form": form,
        "raw_text": primary,
        "provenance": place(hay, primary, anchor, f"{where}.instrument"),
        "stated_currency": None,
        "stated_venue": None,
        "resolved": None,          # filled by enrichment at runtime, never labelled
    }
    for field, value in (("name", name), ("ticker", ticker), ("isin", isin)):
        if value and value != primary:
            out[f"also_{field}"] = {"raw_text": value,
                                    "provenance": place(hay, value, anchor, f"{where}.{field}")}
    if cur := str(order.get("currency") or "").strip():
        out["stated_currency"] = {"value": cur.upper(),
                                  "provenance": place(hay, cur, anchor, f"{where}.currency")}
    return out


def line_of(hay: str, order: dict, index: int, after: int,
            default_account) -> tuple[dict, int]:
    where = f"orders[{index}]"
    anchor = anchor_for(hay, order, after, where)

    execution = {
        "order_type":  tri(hay, order.get("order_type"), anchor, where, "order_type"),
        "limit_price": tri(hay, order.get("limit_price"), anchor, where, "limit_price"),
        "strategy":    tri(hay, order.get("strategy"), anchor, where, "strategy"),
        "horizon":     tri(hay, order.get("horizon"), anchor, where, "horizon"),
        "expiry":      {"state": "UNRESOLVED"},
    }
    if execution["order_type"].get("value") == "LIMIT" and \
            execution["limit_price"]["state"] != "MAPPED":
        raise LabelError(f"{where}: order_type is LIMIT but no limit_price. "
                         "A limit order without a price is not a draft anyone can act on.")
    if execution["limit_price"]["state"] == "MAPPED":
        execution["limit_price"]["value"] = to_number(
            execution["limit_price"]["raw_text"], f"{where}.limit_price")

    account = order.get("account") or default_account
    line = {
        "line_index": index,
        "side":        tri(hay, order.get("side"), anchor, where, "side"),
        "instrument":  instrument_of(hay, order, anchor, where),
        "quantity":    quantity_of(hay, order, anchor, where),
        "execution":   execution,
        "trade_date":  tri(hay, order.get("trade_date"), anchor, where, "trade_date"),
        "account_ref": tri(hay, account, anchor, where, "account"),
        "unmapped":    [],
    }

    for item in order.get("unmapped") or []:
        if not isinstance(item, dict) or "raw" not in item:
            raise LabelError(f"{where}.unmapped: each entry needs `field:` and `raw:`.")
        line["unmapped"].append({
            "field": item.get("field"),
            "state": "UNMAPPED",
            "raw_text": str(item["raw"]),
            "provenance": place(hay, str(item["raw"]), anchor, f"{where}.unmapped"),
        })

    return line, (anchor + 1 if anchor is not None else after)


# ------------------------------------------------------------ validation ----

def load_tags(repo: Path) -> set[str]:
    path = repo / "corpus" / "schema" / "tags.yaml"
    if not path.exists():
        raise LabelError(f"missing tag vocabulary at {path}")
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {t for group in doc.values() if isinstance(group, dict) for t in group}


def check_label(label: dict, vocab: set[str], where: str) -> list[str]:
    problems = []
    if label.get("split") not in ("dev", "holdout"):
        problems.append(f"{where}: split must be dev or holdout, got {label.get('split')!r}")

    tags = [t for t in (label.get("tags") or []) if t]
    for t in tags:
        if t not in vocab:
            problems.append(f"{where}: unknown tag {t!r}. Add it to corpus/schema/tags.yaml "
                            "in its own commit, or use one that is already there.")
    if not tags:
        problems.append(f"{where}: no tags. At minimum say what shape the email is.")

    orders = label.get("orders") or []
    negative = any(t.startswith("negative-") for t in tags)
    if negative and orders:
        problems.append(f"{where}: tagged negative but carries {len(orders)} order(s). "
                        "One of the two is wrong, and this is exactly the confusion "
                        "that lets a fabrication score as correct.")
    if not orders and not negative:
        problems.append(f"{where}: no orders and no negative-* tag. If the email really "
                        "contains no instruction, tag it so it counts as a negative.")

    for i, o in enumerate(orders):
        if not isinstance(o, dict):
            problems.append(f"{where}: orders[{i}] is not a mapping")
            continue
        if not (o.get("side") and (o.get("instrument") or o.get("ticker") or o.get("isin"))):
            problems.append(f"{where}: orders[{i}] needs at least a side and one way to "
                            "identify the instrument. If the client was vaguer than that, "
                            "record what they did say and note it in `notes:`.")

    for i, d in enumerate(label.get("disagreements") or []):
        if isinstance(d, dict) and not d.get("resolved"):
            problems.append(f"{where}: disagreements[{i}] is unresolved. Settle it, write the "
                            "rule into docs/corpus-spec.md, then build.")
    return problems


# --------------------------------------------------------------- per dir ----

def build(d: Path, repo: Path, vocab: set[str], check_only: bool) -> tuple[bool, list[str]]:
    label_path, eml = d / "label.yaml", d / "source.eml"
    if not label_path.exists() or not eml.exists():
        return False, [f"{d.name}: needs both label.yaml and source.eml"]

    label = yaml.safe_load(label_path.read_text(encoding="utf-8")) or {}
    if problems := check_label(label, vocab, d.name):
        return False, problems

    msg = BytesParser(policy=policy.default).parsebytes(eml.read_bytes())
    if part := msg.get_body(("plain",)):
        text, part_name = part.get_content(), "BODY_TEXT"
    elif part := msg.get_body(("html",)):
        text, part_name = part.get_content(), "BODY_HTML"
    else:
        return False, [f"{d.name}: no text body"]

    # Offsets are character offsets into the NFC-normalised body. Normalise
    # once, here, and record it — an offset is meaningless without knowing
    # which normalisation it counts characters in.
    hay = unicodedata.normalize("NFC", text)
    cut, excluded = message_zone(hay)

    try:
        lines, after = [], 0
        for i, order in enumerate(label.get("orders") or []):
            line, after = line_of(hay, order, i, after, label.get("account"))
            lines.append(line)

        constraints = []
        for c in label.get("constraints") or []:
            if not str(c).strip():
                continue
            constraints.append({"state": "MAPPED", "raw_text": str(c).strip(),
                                "provenance": place(hay, str(c), None, f"{d.name}.constraints")})
    except LabelError as exc:
        return False, [f"{d.name}: {exc}"]

    capture = {
        "_schema": SCHEMA,
        "_generated": "scripts/build_fixture.py from label.yaml — do not edit by hand",
        "envelope": {
            "sender_address": str(msg["From"] or ""),
            "subject": str(msg["Subject"] or ""),
            "language": label.get("language") or "en",
            "normalisation": "NFC",
            "live_region": {"part": part_name, "start": 0, "end": cut, "excluded": excluded},
        },
        "lines": lines,
        "constraints": constraints,
        "unmapped": [],
    }

    out = d / "expected.capture.json"
    if not check_only:
        out.write_text(json.dumps(capture, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    loose = [
        f"{ln['line_index']}.{f}"
        for ln in lines for f, v in (("side", ln["side"]), ("trade_date", ln["trade_date"]),
                                     ("account", ln["account_ref"]))
        if isinstance(v, dict) and v.get("provenance", {}).get("matched") not in (None, "exact")
    ]
    note = []
    if loose:
        note.append(f"{d.name}: matched loosely (whitespace or case): {', '.join(loose[:6])}")
    if str(label.get("notes") or "").strip().endswith("TODO"):
        note.append(f"{d.name}: notes: still says TODO")
    if not (label.get("labelled_by") or []):
        note.append(f"{d.name}: labelled_by is empty")

    unresolved = sum(
        1 for ln in lines for v in (ln["side"], ln["trade_date"], ln["account_ref"],
                                    ln["execution"]["order_type"], ln["execution"]["strategy"],
                                    ln["execution"]["horizon"])
        if v.get("state") == "UNRESOLVED")
    print(f"  {d.name}: {len(lines)} line(s), {unresolved} unresolved field(s)"
          f"{'  [check only]' if check_only else ''}")
    for n in note:
        print(f"      ~ {n}")
    return True, []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="label.yaml -> expected.capture.json")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--check", action="store_true", help="validate and derive, write nothing")
    args = ap.parse_args(argv)

    repo = Path(__file__).resolve().parent.parent
    try:
        vocab = load_tags(repo)
    except LabelError as exc:
        print(exc, file=sys.stderr)
        return 1

    dirs: list[Path] = []
    for p in map(Path, args.paths):
        if (p / "label.yaml").exists():
            dirs.append(p)
        elif p.is_dir():
            dirs.extend(sorted(c for c in p.iterdir() if (c / "label.yaml").exists()))
    if not dirs:
        print("no fixture directories with a label.yaml found", file=sys.stderr)
        return 1

    ok, failures = 0, []
    for d in dirs:
        good, problems = build(d, repo, vocab, args.check)
        ok += good
        failures.extend(problems)

    if failures:
        print(f"\n{len(dirs) - ok} of {len(dirs)} fixture(s) NOT built:\n", file=sys.stderr)
        for f in failures:
            print(f"  - {f}\n", file=sys.stderr)
        return 2

    print(f"\n{ok}/{len(dirs)} built.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
