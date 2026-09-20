# ============================================================ CM-4 spans ===
#
# Paste into evals/scoring.py after `score_field`, before `FixtureScore`.
# Add `import re` and `import unicodedata` at the top of the module.
#
# WHY THIS EXISTS
#
# CM-4: "Every leaf value carries Provenance naming the source part and span.
# A span that does not contain the value it claims is a defect even when the
# value is correct."
#
# Nothing enforced that, and the cost showed up during 010: the extractor
# stamped offsets computed against concatenated live-text as though they
# indexed the full body. Every value was right. Every span was wrong. The
# corpus reported no problem, because scoring compared values and never
# looked at spans — so a reviewer would have been shown the wrong words with
# full confidence.
#
# WHY IT IS A HARD GATE
#
# Spans are computed by deterministic code from text the model quoted. That
# code either locates correctly or is broken; there is no "the model found
# this one hard" case, and so no reason to budget for it the way misses are
# budgeted. A span defect is always a bug, and a bug in the one mechanism a
# human uses to check the agent's work before a trade is released.

_WS = re.compile(r"\s+")


def _squash(s: str) -> str:
    return _WS.sub(" ", s).strip()


@dataclass(frozen=True)
class SpanDefect:
    path: str                 # "lines[0].instrument.provenance"
    reason: str               # mismatch | whitespace-only | out-of-range | missing-provenance
    start: int = -1
    end: int = -1
    claimed: str = ""         # what the node says lives there
    found: str = ""           # what is actually at body[start:end]

    @property
    def critical(self) -> bool:
        """Whitespace-only differences are reported but not gated: a locator
        that matched across a line wrap is sloppy, not wrong, and failing a
        run for it would teach people to stop reading this list."""
        return self.reason != "whitespace-only"

    def __str__(self) -> str:
        if self.reason == "out-of-range":
            return f"{self.path}: span [{self.start}:{self.end}] falls outside the body"
        if self.reason == "missing-provenance":
            return f"{self.path}: mapped value carries no provenance"
        return (f"{self.path}: span [{self.start}:{self.end}] holds {self.found!r} "
                f"but the value claims {self.claimed!r} ({self.reason})")


def _is_provenance(key: str, value: Any) -> bool:
    """A provenance node is any `provenance` / `*_provenance` key carrying
    integer offsets. Matching by shape rather than by a list of known paths
    means a field added later is covered without anyone remembering to."""
    return (
        (key == "provenance" or key.endswith("_provenance"))
        and isinstance(value, dict)
        and isinstance(value.get("start"), int)
        and isinstance(value.get("end"), int)
    )


def _compare(path: str, claimed: str, found: str, start: int, end: int,
             out: list[SpanDefect]) -> None:
    if claimed == found:
        return
    reason = "whitespace-only" if _squash(claimed) == _squash(found) else "mismatch"
    out.append(SpanDefect(path, reason, start, end, claimed, found))


def _check_node(node: dict, path: str, body: str, out: list[SpanDefect]) -> None:
    for key, prov in node.items():
        if not _is_provenance(key, prov):
            continue
        here = f"{path}.{key}" if path else key
        start, end = prov["start"], prov["end"]

        if not (0 <= start <= end <= len(body)):
            out.append(SpanDefect(here, "out-of-range", start, end,
                                  str(prov.get("text", "")), ""))
            continue

        found = body[start:end]

        # 1. Provenance carries its own copy of the text. It must match.
        if isinstance(prov.get("text"), str):
            _compare(here, prov["text"], found, start, end, out)

        # 2. The value's raw_text must match its own span. A node whose
        #    raw_text and span disagree is a correct value pointing at the
        #    wrong words — exactly what CM-4 names.
        if key == "provenance" and isinstance(node.get("raw_text"), str):
            _compare(f"{path}.raw_text" if path else "raw_text",
                     node["raw_text"], found, start, end, out)

    # Mapped but unverifiable. Not wrong, but it defeats the same purpose.
    mapped = node.get("state") in ("Mapped", "MAPPED")
    quantified = node.get("kind") in ("Absolute", "EntirePosition")
    if (mapped or quantified) and not any(_is_provenance(k, v) for k, v in node.items()):
        out.append(SpanDefect(path or "(root)", "missing-provenance"))


def _walk(doc: Any, path: str, body: str, out: list[SpanDefect]) -> None:
    if isinstance(doc, dict):
        _check_node(doc, path, body, out)
        for key, value in doc.items():
            if not _is_provenance(key, value):
                _walk(value, f"{path}.{key}" if path else key, body, out)
    elif isinstance(doc, list):
        for i, value in enumerate(doc):
            _walk(value, f"{path}[{i}]", body, out)


def check_spans(doc: Any, body: str) -> list[SpanDefect]:
    """Verify every provenance span in `doc` against the body it indexes.

    `body` must carry the normalisation the offsets were counted in. The
    envelope declares it, so use `body_for` rather than passing raw text —
    NFC drift produces defects that look like locator bugs and are not.
    """
    out: list[SpanDefect] = []
    _walk(doc, "", body, out)
    return out


def body_for(doc: dict, raw_body: str) -> str:
    """Normalise a raw body the way the document says its offsets were
    counted. Unknown normalisation is refused rather than guessed: scoring
    spans against the wrong normalisation is worse than not scoring them."""
    declared = (doc.get("envelope") or {}).get("normalisation", "NFC")
    if declared not in ("NFC", "NFD", "NFKC", "NFKD"):
        raise ValueError(f"unknown normalisation {declared!r} in envelope")
    return unicodedata.normalize(declared, raw_body)


# ------------------------------------------------- wiring into the report ---
#
# In FixtureScore, REPLACE:
#
#     provenance_failures: int = 0
#
# with:
#
#     span_defects: list[SpanDefect] = field(default_factory=list)
#
#     @property
#     def provenance_failures(self) -> int:
#         return sum(1 for d in self.span_defects if d.critical)
#
# In RunReport, ADD these two, and the gate line below:
#
#     @property
#     def provenance_failures(self) -> int:
#         return sum(s.provenance_failures for s in self.scores)
#
#     @property
#     def span_warnings(self) -> int:
#         return sum(1 for s in self.scores for d in s.span_defects if not d.critical)
#
# In RunReport.gate(), after the fabrication check:
#
#         if self.provenance_failures:
#             failures.append(
#                 f"{self.provenance_failures} provenance defect(s) - a span does "
#                 "not contain the value it claims (CM-4). Always a code bug.")
#
# The runner calls it per fixture:
#
#     body = body_for(expected, raw_body)
#     score.span_defects = check_spans(actual, body)
#
# Note `actual`, not `expected`. Checking the fixtures is worth doing once, as
# a corpus health check, but the thing that regresses is the extractor.
