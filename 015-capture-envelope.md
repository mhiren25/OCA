<!-- draft proposal · import with /opsx:new 015-capture-envelope then /opsx:ff
     spec: capture-model -->

# 015-capture-envelope

## Why

001 built the primitives — `Provenance`, the `Mapped` / `Unmapped` /
`Unresolved` tri-state, the `Quantity` union, `PositionSnapshot` — and
explicitly stopped there. Nothing composes them into the thing one email
produces.

That gap is now load-bearing in three places:

- **010** has no return type for the extractor.
- **013** has nothing to deserialise a fixture into.
- **The corpus is already written in a shape no model can express.**
  `scripts/build_fixture.py` emits an envelope with `lines[]` because the
  domain model document describes one. So there is a capture schema the
  fixtures assume and the code cannot state.

The third is the urgent one. Until the model exists, nothing checks that the
labels and the code agree, and the first symptom would be an eval reporting
scoring failures that are really shape failures — which is the most expensive
kind of wrong number, because it looks like a model problem and sends you off
tuning a prompt.

CM-5 and CM-6 in `docs/specs-draft/capture-model.md` describe this type and
were never turned into an approved change. This is that change.

## What changes

`src/trade_capture/domain/capture.py` (new). Composition only — no new
primitives, no validation logic beyond what the types enforce.

- **`LiveRegion`** — `part`, `start`, `end`, `excluded: list[str]`.
  Which slice of which MIME part the client's own words occupy.

- **`EmailEnvelope`** — `sender_address`, `subject`, `language`,
  `normalisation: Literal["NFC"]`, `live_region: LiveRegion`.
  `normalisation` is not decoration: an offset is meaningless without knowing
  which normalisation it counts characters in.

- **`InstrumentRef`** — tri-state, plus `form: Literal["NAME","TICKER","ISIN"]`,
  `raw_text`, `provenance`, `stated_currency`, `stated_venue`, `resolved`.

- **`ExecutionTerms`** — `order_type`, `limit_price`, `strategy`, `horizon`,
  `expiry`, each tri-state.

- **`UnmappedInstruction`** (CM-6) — `field`, `raw_text`, `reason`,
  `priority`, `provenance`. Raw text preserved verbatim.

- **`OrderIntent`** (CM-5) — `line_index`, `side`, `instrument: InstrumentRef`,
  `quantity: Quantity`, `execution: ExecutionTerms`, `trade_date`,
  `account_ref`, `unmapped: list[UnmappedInstruction]`.

- **`CaptureEnvelope`** — `envelope: EmailEnvelope`,
  `lines: list[OrderIntent]`, `constraints: list[...]`,
  `unmapped: list[UnmappedInstruction]`. The top-level type.

## Three decisions to make explicit

**`InstrumentRef.resolved` is `None` in everything this change touches** —
extraction output and every fixture.

Resolution happens later, and an LLM does take part in it: code calls the MCP
with the client's raw text, the MCP returns candidate instruments, and a
second, separate LLM call chooses among them. Name matching is semantic —
distinguishing an ORD line from a CDI line of the same issuer is not
string-distance work — so that call earns its place. It is simply not this
one, and its output is not what a fixture records.

Two reasons a fixture's `resolved` stays `None`, beyond sequencing:

- CO-1: fixtures are labelled at capture level. The label records what the
  client said, not what the instrument master answered.
- Reference data moves. A fixture carrying a resolved identifier rots the
  next time the master changes, and then measures the MCP rather than the
  extraction.

So a populated `resolved` arriving out of extraction, or sitting in a
fixture, is a defect. Out of enrichment it is the expected result.

**A note for whoever builds enrichment** (005, not this change): the
selection call must choose from the candidate list or answer "none of these",
and must never emit an identifier that was not in the list. A fabricated ISIN
is the worst fabrication in the system — it produces a draft for a real,
wrong security, and it reads as correct to a reviewer. "None of these" is a
legitimate outcome and resolves to `Unresolved`.

**`EntirePosition.resolved_position` is `None` at capture, for the same
reasons.** "Sell all" extracts as `EntirePosition` with `client_asserted`
holding the figure the client quoted, if any, and nothing else. Enrichment
later asks the positions MCP and fills a `PositionSnapshot` — quantity,
`as_of`, source — which is what that 001 primitive is for. Unlike instrument
resolution this needs no LLM: account plus resolved instrument is a lookup.
It is also ordered *after* instrument resolution, since the positions service
needs an identifier; an `Unresolved` instrument leaves the position
`Unresolved` too.

A fixture's `resolved_position` is always `None`. Positions change daily, so
a fixture carrying one would be stale within a week and would be measuring
the positions service rather than the extraction.

Per CM-3, when `client_asserted` and `resolved_position` disagree both
survive to the reviewer and the agent reconciles nothing. Which of them, if
either, becomes `orderQty` is a mapping decision (011) and is **not yet
made** — leaving the quantity blank for a human is a legitimate answer.

**A resolved position is a client holding**, so it must never enter an LLM
prompt and never reach a cassette. The natural mistake is a later "review the
enriched envelope" model call, which would put holdings into recorded
exchanges and therefore into git. Worth a test that asserts it.

**Constraints are email-level, not per line.** "Please ensure there is no
short selling for sell order" governs the message, not row six. Attaching it
to a line would make it look scoped to that order.

**Zero lines is valid** (CM-5) and is how a negative fixture is represented —
an enquiry, a confirmation, a message with no instruction in it. An empty
`lines[]` is a real answer, not a failure to parse.

## Acceptance

- `CaptureEnvelope.model_json_schema()` generates;
  `python scripts/gen_schema.py` writes `corpus/schema/capture.v1.schema.json`
  and finds the model without editing its `PREFERRED` list.
- **Every fixture in `corpus/fixtures/` round-trips**:
  `CaptureEnvelope.model_validate(...)` then `.model_dump()` equals the file,
  ignoring underscore-prefixed keys. `scripts/gen_schema.py --validate` passes.
- CM-1 through CM-6 each have a test.

Where the model and `scripts/build_fixture.py` disagree, **the model is
right** — the spec decides the shape and the writer follows. Report the
mismatch rather than loosening the model to accept what the writer happens to
emit, and rather than editing fixtures by hand: `corpus/` is
CODEOWNERS-protected, and the fixtures were labelled before this model
existed, so a disagreement is information about which side is wrong.

## Out of scope

The extractor and prompt (010). Mapping to `OrderRequest`. Enrichment. Any
validation rule that is not a type constraint — those are 003.

## Sequencing

Before 010. The extractor's return type is this.
