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

**`InstrumentRef.resolved` is always `None` in a capture.** The LLM never
resolves an instrument; the enrichment chain does, later, against the MCP. A
capture with a populated `resolved` means something upstream invented an
identifier, and a fixture with one is a labelling error.

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
