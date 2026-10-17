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

## Amendment — reading enriched values

*Added 2026-10-17, once 005 and 023 made these fields non-null.*

**No second mapper.** Resolvers write capture-model paths
(`instrument.resolved`, `quantity.resolved_position`), so they enrich the
**envelope** and this mapper reads an envelope with more filled in. The
pipeline gains a stage, not a component:

```
capture  →  enrich (005)  →  map (this)  →  deny-list  →  payload
```

One component writes `OrderRequest`. Two would be the same failure 005's
duplicate-`writes` check guards against, one level up.

Three things follow, and they are the whole amendment:

- **The precedence table's third row stops being unset** — see below.
- **A resolved instrument carries more than free text** into the payload.
  Exactly what — ISIN plus market, a listing identifier, something else —
  depends on what `OrderRequest` accepts, which **nobody has confirmed**.
  Ask the Draft Order team alongside the annotation field; it also decides
  what 023's resolver must return.
- **A resolved value is not a stated value.** See the origin rule.

### Origin, not just presence

The mapper today sees two states: Mapped, so write it; Unresolved or
Unmapped, so leave it unset. Enrichment adds a third — **filled by a
service** — and flattening it into "Mapped" loses the distinction a reviewer
needs.

*The client said 91,647* and *the positions service said 91,647 at 14:02*
are different claims, and only one of them is the client's instruction. 005
records which resolver wrote a field; this mapper must carry that through to
the review annotation and the page, not discard it on the way to the
payload.

The payload itself may have nowhere to express it — that is the annotation
field again. The envelope and the page must keep it regardless.

## Not blocked on enrichment

Before the resolvers existed, `instrument.resolved` and
`quantity.resolved_position` were always `None` and the mapper left
everything downstream of enrichment unset.

That is not a limitation to apologise for *for most fields*: incomplete
drafts are a supported outcome of the Draft Order service, and the whole
two-schema design exists so that "the client said *sell all*" produces a
usable draft rather than a failure. A draft with `orderQty` unset is a
correct output, not a broken one.

**The instrument is the exception, and the original draft of this proposal
had it wrong.** The Draft Order service will not accept an order without an
ISIN, so an unresolved instrument does not produce a thin draft — it
produces none. That line yields no `OrderRequest`, a blocking review item,
and no effect on the other lines in the email. 023 carries the detail.

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

| client said | `orderQty` | origin |
|---|---|---|
| `35,300` | 35,300 | client |
| `sell all (91,647)` | 91,647 | client |
| `sell all`, position resolved | the resolved figure | **positions service** |
| `sell all`, no position resolver, or it found nothing | unset + review item | — |

The rule above the table is unchanged: `client_asserted` wins whenever it
exists, and the positions service is called only for sell-all. The third
row is the only one enrichment touches, and the fourth stays a correct
output rather than a failure.

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
- `EntirePosition` with no figure and no resolved position leaves `orderQty`
  unset plus a review annotation — still a correct output, not a failure.
- `EntirePosition` with no figure but a resolved position maps that figure,
  and the annotation records that the positions service supplied it.
- A stated figure and a resolved position that disagree map the **stated**
  one; both survive in the envelope and the disagreement is a review item.
- A value filled by a resolver is distinguishable from a client-stated value
  everywhere downstream of the mapper — asserted, because flattening the two
  is invisible once it has happened.
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
