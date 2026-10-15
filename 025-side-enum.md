<!-- draft proposal · import with /opsx:new 025-side-enum then /opsx:ff
     spec: capture
     before: 023 (the resolver reads what this captures) -->

# 025-side-enum

## Why

Funds subscribe and redeem on the primary market; equities and bonds trade
secondary. 023 needs to know which segment an order is for, and the only
place that information exists is the client's own words.

If capture flattens *"subscribe to X"* into `BUY`, the distinction is
destroyed before any resolver runs and nothing downstream reconstructs it.

## What the enum becomes

```
BUY | SELL | SUBSCRIBE | REDEEM
```

This follows directly from the two-schema principle: **the capture model
records what the client said**, and a client who wrote "subscribe" did not
write "buy". `OrderRequest` is a fixed external schema and may well have
only two sides — decomposing for it is the mapper's job, not capture's.

## One derived fact: direction

| captured `side` | direction |
|---|---|
| `BUY` | IN |
| `SELL` | OUT |
| `SUBSCRIBE` | IN |
| `REDEEM` | OUT |

**Direction drives 023's `buyAllowed` / `sellAllowed` check.** A subscribe
is a buy-side action for permission purposes, so that check reads direction
and never `side` directly. One place derives it; nothing else re-decides.

**No market segment is derived.** Funds execute on both primary and
secondary markets, so there is no rule mapping a side to a segment that is
safe to act on — and a filter built on an unsafe rule silently resolves to
the wrong listing instead of asking. 023 carries the reasoning; the point
here is that `SUBSCRIBE` does **not** imply primary-only, and nothing in
this change should be read as saying it does.

## Check this before building

The screenshot shows `SUBSCRIBE` rendering on the page today. Either the
enum already carries it, or **a value outside the enum reached the page**,
which would mean the capture schema is not being enforced at the boundary.

Find out which. The second is a bigger finding than this proposal — it would
mean other out-of-vocabulary values pass silently too, and that is a
fabrication surface nobody is watching.

## What else moves

**The prompt** must name all four and say when each applies, or the model
will keep producing `BUY` for a subscription most of the time and
`SUBSCRIBE` occasionally — which is worse than either, because the
inconsistency looks like a model problem rather than a prompt gap.

**The mapper (011)** decomposes for `OrderRequest`: `SUBSCRIBE` becomes
whatever that service's side field accepts, plus the primary-market
indication if it has one. If it has no way to express the segment, that is a
review annotation and a question for the Draft Order team — the same
conversation as the annotation field.

**The corpus.** There are barely any fund emails, so these enum values would
ship untested. Two things follow, and the second matters more:

- Fixtures for a subscription and a redemption, labelled before the prompt
  changes, so the change is measured rather than assumed.
- **`tags.yaml` gains `fund-subscription` and `fund-redemption`.** The
  coverage checklist from 014 then shows them as *none yet* to every tester
  and domain expert who opens the page, which is the mechanism that gets the
  emails in — far better than asking around.

## Acceptance

- The enum carries four values, and a fifth value is rejected at the capture
  boundary with a test that proves it.
- Direction derives from `side` in one place, and 023's permission check
  reads it rather than `side`.
- No market segment is derived from `side`, and nothing filters on one.
- A subscription email captures `SUBSCRIBE`, and its provenance quotes the
  client's own word.
- The mapper produces a valid `OrderRequest` for all four values.
- `tags.yaml` carries the two new tags and the coverage checklist shows them.
- **The eval baseline does not move.** No existing fixture uses the new
  values, so a shift means the prompt change disturbed something else.

## Out of scope

Anything about how the Draft Order service represents a subscription — that
is a question for its owners, and the mapper carries a review annotation
until they answer.
