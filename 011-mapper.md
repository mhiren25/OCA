<!-- draft proposal · import with /opsx:new 011-mapper then /opsx:ff
     spec: mapping -->

# 011-mapper

## Why

Everything built so far ends at a `CaptureEnvelope` — a record of what the
client said. Nothing turns that into the payload the Draft Order service
accepts, so there is no Order to return from an API and no draft for a human
to review. This is that step.

It is also where a new class of error becomes possible: capture correct,
mapping wrong. Extraction is measured at 97%+ with zero fabrications; the
mapping has never been measured at all.

## Not blocked on enrichment

`instrument.resolved` and `quantity.resolved_position` are always `None`
today — the MCP resolvers do not exist yet. The mapper maps what capture
holds and leaves everything downstream of enrichment unset.

That is not a limitation to apologise for: incomplete drafts are a supported
outcome of the Draft Order service, and the whole two-schema design exists so
that "the client said *sell all*" produces a usable draft rather than a
failure. A draft with `orderQty` unset and the instrument unresolved is a
correct output, not a broken one.

## Quantity precedence — decided

**`client_asserted` takes precedence over `resolved_position`.** The client
asked for a number; filling a different one is the agent overriding the
instruction it was asked to capture.

**The positions service is called only for "sell all".** No other case needs
it, so no other case pays for the call or the coupling.

If the client's figure is stale, the validation service already checks it
when a draft is submitted from the GUI. That control exists, it sits closer
to the moment of action, and it has better information than the agent does.
Re-implementing it here would duplicate someone else's check with a worse
view of the world.

So in practice today:

| client said | `orderQty` |
|---|---|
| `35,300` | 35,300 |
| `sell all (91,647)` | 91,647 |
| `sell all` | unset until the positions resolver exists |

CM-3 still holds — when both values exist they both survive in the capture
model, and neither overwrites the other. This decides only which one reaches
the payload.

## What changes

`src/trade_capture/mapping/mapper.py`

- `to_order_requests(envelope) -> list[OrderRequest]` — **one request per
  `OrderIntent`**. A three-order email produces three drafts.
- Mapped capture values become payload fields. Unresolved and Unmapped
  capture values leave their payload field unset. Never a placeholder, never
  a default dressed as a value.
- `externalOrderReference` = `TCA-<ULID>-<line_index>`, the idempotency key,
  since the service does not accept a caller-supplied `clOrdId`.
- `clOrdId` is never set — the service generates it.
- Default `timeInForce` to DAY **here**, where it is visible and testable.
  018 removed it from extraction for exactly this reason.

### The draft-only invariant

The deny-list in `mapping/denylist.py` already exists and already includes
`lifecycleData.canSubmit`. The mapper must run every payload through it
before returning, and a denied field present in an outgoing payload is an
exception, not a warning.

This stops being theoretical the moment the API lands: a returned
`OrderRequest` is one HTTP call away from being submitted by whatever calls
it next.

### The 256-character budget

`execInstructions` is free text and the service **silently trims at 256**.
Silent truncation of a client's execution instruction is the kind of defect
nobody finds until it matters, so the mapper trims deliberately, to a budget
below the limit, and records that it did. Our trim must never let theirs
fire.

Note the name collision that has caused confusion before: `execInstrs` is the
enum list, `execInstructions` is the 256-char free text. They are different
fields.

### Sentinels are values, not absences

`price = 0.0` means market-priced. `targetStrategy = UNSET` is a real,
meaningful value. Neither may ever be written to mean "we could not parse
this" — a reviewer reading a payload cannot tell the difference, and that is
precisely the fabrication class this project gates at zero.

### Review annotations — built, not yet emitted

The mapper produces a structured list of items a reviewer must act on:

- a value the agent could not determine and a human must supply
- a value the client stated that the schema cannot hold (`Unmapped`)
- (later) a value where two sources disagreed

The payload field to carry this does not exist — it is an extension being
requested from the Draft Order service team. So the mapper **returns these
alongside the payload and does not write them into it** until that field
lands. Building the structure now means the extension is a one-line change
when it arrives, and the API can surface the same information immediately.

Two rules on it from the start: entries are assembled from a fixed set of
reasons, never free-form model prose, and any client text quoted into one is
clearly delimited. That field renders in a reviewer's screen, and the email
it came from is untrusted input.

**Keep the list short.** An experienced trader fills this form manually in
15–20 seconds. A draft carrying more than two or three things to check costs
more attention than it saves, and loses the user. The discipline is not
cosmetic — it is the difference between a tool people use and one they route
around.

## Acceptance

- A three-order email produces three `OrderRequest`s with distinct
  `externalOrderReference`s.
- Unresolved capture fields leave their payload fields unset — asserted
  field by field, not in aggregate.
- Every returned payload passes the deny-list; a test that injects a denied
  field fails loudly.
- A 300-character client instruction is trimmed by us, below the service's
  limit, and the trim is recorded.
- `price=0.0` round-trips as market-priced and is never produced from an
  unparsed input.
- `EntirePosition` with a stated figure maps that figure to `orderQty`.
- `EntirePosition` with no figure leaves `orderQty` unset plus a review
  annotation, until the positions resolver exists.
- Golden payload tests for the fixtures already in the corpus.

## Out of scope

Enrichment and the resolvers. The API entrypoint (next). The annotation
payload field (blocked on the service extension). Deterministic validators
(003).

## After this lands

Measure the **clean-draft rate** — the share of fixtures producing a draft
that needs no human intervention. Field-level accuracy is the right metric
for tuning extraction; clean-draft rate is the one that decides whether
anyone uses this, and the two can be far apart.
