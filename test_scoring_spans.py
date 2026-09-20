"""CM-4: a span must contain the value it claims.

Each test here is one way the check earns its place. The first is the bug
found during 010 — offsets computed against concatenated live text, stamped
as though they indexed the full body. Every value correct, every span wrong,
and the corpus silent about it.
"""

from __future__ import annotations


import pytest

from evals.scoring import SpanDefect, body_for, check_spans

BODY = "Hi,\n\nPlease sell all (91,647) shares of Sunrise Energy Metals.\n"


def prov(start: int, end: int) -> dict:
    return {"start": start, "end": end, "text": BODY[start:end], "matched": "exact"}


def mapped(start: int, end: int) -> dict:
    return {"state": "Mapped", "raw_text": BODY[start:end],
            "value": BODY[start:end], "provenance": prov(start, end)}


@pytest.fixture
def doc() -> dict:
    return {
        "envelope": {"normalisation": "NFC"},
        "lines": [{
            "line_index": 0,
            "side": mapped(12, 16),                       # "sell"
            "instrument": mapped(40, 61),                 # "Sunrise Energy Metals"
            "quantity": {
                "kind": "EntirePosition",
                "raw_text": BODY[17:20],                  # "all"
                "provenance": prov(17, 20),
                "client_asserted": 91647,
                "client_asserted_provenance": prov(22, 28),   # "91,647"
            },
            "trade_date": {"state": "Unresolved"},
        }],
    }


def test_fixture_offsets_point_where_the_comments_say():
    """`mapped()` derives its text FROM the body, so a fixture with wrong
    offsets is still internally consistent and sails through every other
    test here. Pin the offsets against the words themselves or this whole
    file quietly tests nothing."""
    assert BODY[12:16] == "sell"
    assert BODY[17:20] == "all"
    assert BODY[22:28] == "91,647"
    assert BODY[40:61] == "Sunrise Energy Metals"


def test_clean_document_has_no_defects(doc):
    assert check_spans(doc, BODY) == []


def test_uniformly_shifted_spans(doc):
    """The 010 bug. Offsets counted in one coordinate frame, reported in
    another — so every value is right and every span points at the wrong
    words. Nothing else in scoring can see this."""
    for line in doc["lines"]:
        for node in (line["side"], line["instrument"], line["quantity"]):
            p = node["provenance"]
            p["start"] += 3
            p["end"] += 3

    defects = [d for d in check_spans(doc, BODY) if d.critical]

    # Every shifted field is caught. A span near the end of the body runs off
    # it and reports out-of-range instead of mismatch — same failure, and
    # asserting the exact reason here would make the test about the offsets
    # chosen above rather than about the shift being detected at all.
    assert {"lines[0].side", "lines[0].instrument", "lines[0].quantity"} <= {
        d.path.rsplit(".", 1)[0] for d in defects
    }
    assert all(d.reason in ("mismatch", "out-of-range") for d in defects)


def test_raw_text_disagrees_with_its_own_span(doc):
    """A correct-looking value pointing at words that do not say it."""
    doc["lines"][0]["side"]["raw_text"] = "buy"
    defects = [d for d in check_spans(doc, BODY) if d.critical]
    assert [d.path for d in defects] == ["lines[0].side.raw_text"]
    assert defects[0].found == "sell"


def test_span_outside_the_body(doc):
    doc["lines"][0]["side"]["provenance"].update(start=9_000, end=9_004)
    defects = check_spans(doc, BODY)
    assert [d.reason for d in defects] == ["out-of-range"]


def test_mapped_value_without_provenance(doc):
    del doc["lines"][0]["instrument"]["provenance"]
    defects = [d for d in check_spans(doc, BODY) if d.critical]
    assert [d.reason for d in defects] == ["missing-provenance"]


def test_unresolved_needs_no_provenance(doc):
    """Unresolved is a real answer, not a missing one. It has nothing to
    point at and must not be penalised for that."""
    doc["lines"][0]["side"] = {"state": "Unresolved"}
    assert check_spans(doc, BODY) == []


def test_nested_provenance_is_reached(doc):
    """`client_asserted_provenance` is nested inside a Quantity variant. The
    walk matches by shape, not by a list of known paths, so a field added
    later is covered without anyone remembering to add it here."""
    doc["lines"][0]["quantity"]["client_asserted_provenance"].update(start=0, end=2)
    defects = [d for d in check_spans(doc, BODY) if d.critical]
    assert [d.path for d in defects] == ["lines[0].quantity.client_asserted_provenance"]


def test_whitespace_difference_is_reported_but_not_gated(doc):
    """A locator that matched across a line wrap is sloppy, not wrong.
    Gating on it would train people to ignore the list."""
    body = BODY.replace("Sunrise Energy", "Sunrise\nEnergy")
    doc["lines"][0]["instrument"]["raw_text"] = "Sunrise Energy Metals"
    doc["lines"][0]["instrument"]["provenance"]["text"] = "Sunrise Energy Metals"

    defects = check_spans(doc, body)
    assert defects, "a whitespace difference should still be reported"
    assert not any(d.critical for d in defects)


def test_body_for_refuses_unknown_normalisation(doc):
    doc["envelope"]["normalisation"] = "NFQ"
    with pytest.raises(ValueError, match="NFQ"):
        body_for(doc, BODY)


def test_body_for_applies_declared_normalisation():
    composed, decomposed = "\u00e9", "e\u0301"   # é, and e + combining acute
    doc = {"envelope": {"normalisation": "NFC"}}
    assert body_for(doc, decomposed) == composed


def test_defect_message_names_both_texts():
    d = SpanDefect("lines[0].side.provenance", "mismatch", 10, 14, "sell", "buy ")
    assert "sell" in str(d) and "buy " in str(d) and "[10:14]" in str(d)
