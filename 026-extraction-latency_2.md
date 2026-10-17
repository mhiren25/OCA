<!-- draft proposal · import with /opsx:new 026-extraction-latency then /opsx:ff
     spec: extraction -->

# 026-extraction-latency

## Why

A measured run shows `extract` at **10,145 ms**. On its own that is
survivable — the contract is async, the gateway allows 60 seconds, and
nobody is blocked. It stops being survivable when 023 adds a lookup per
instrument on top, and a 14-row table has fourteen of them.

So the target is not "make the model fast". It is **keep the whole capture
inside the budget once enrichment is in it**, and extraction is the largest
single piece.

## Sequencing — measure now, fix later or not at all

*Added 2026-10-17.*

**Do the measurement now; hold the fixes until after 023.** Three reasons:

- **The budget may already be fine.** 023 requires bounded concurrency, so
  fourteen lookups are two or three seconds of wall clock, not twenty-one.
  10s extraction plus ~3s enrichment sits comfortably inside a 40-second
  window. An earlier note here implied otherwise by assuming serial calls.
- **The measurement is the cheap half** and it is informative either way. If
  time to first token is most of the ten seconds, levers 1 and 2 would have
  bought almost nothing.
- **Lever 4 is currently unavailable** — no access to another model. When
  that changes it is an afternoon's work and may make the rest unnecessary,
  so doing the hard levers first risks solving by surgery what a config
  change would have solved.

Build 023 with concurrency, measure the real end-to-end total, and reopen
this only if that number does not fit.

## Measure first: two different problems share one number

Before changing anything, split the 10 seconds into **time to first token**
and **generation time**. Streaming gives you both.

They have nothing in common:

- **Time to first token** is queueing, the gateway, the provider. No prompt
  change touches it. If this is 6 of the 10 seconds, everything below is
  wasted effort and the conversation is with whoever runs the endpoint.
- **Generation time** scales with output tokens, roughly linearly. If this
  is the bulk, the levers below apply directly.

024 already logs token counts and latency. This is one run of one fixture.

## The levers, in order of payoff over risk

### 1. Stop emitting what code can derive

The capture model is rich by design, and every field carries its provenance.
**Check whether the model is emitting span offsets.** If it is, that is two
numbers and an excerpt per field, on top of `raw_text` and `value`.

You already have the value locator that finds a quoted string in the body —
it is how `build_fixture.py` derives offsets from `label.yaml`. The same
code can derive them at runtime from `raw_text`, and the model stops
emitting them entirely.

On a rich model with many fields, this is likely the largest single
reduction available, and it costs nothing in accuracy: a span derived by
code from the model's own quoted text is *more* reliable than one the model
counted, and CM-4 still verifies it.

### 2. Omit Unresolved fields rather than stating them

If the model emits `{"state": "Unresolved"}` for fifteen fields it found
nothing for, that is fifteen objects of pure overhead per order.

Let absence mean Unresolved, and have code fill the gaps from the known
field list. **This is safe in the direction that matters**: the failure mode
of an omitted field is a review item, not a wrong value. The fabrication
risk this project gates is invention, and omission is its opposite.

### 3. Prompt caching, if the endpoint supports it

The instructions and schema are byte-identical on every call; only the email
changes. If the OpenAI-compatible endpoint supports caching, this is
configuration rather than code. Worth one question to whoever runs it.

### 4. A faster model, measured

Normally a risky trade. **You are in the unusual position of being able to
settle it empirically in an afternoon** — swap the model, run the corpus,
compare against the committed baseline. If a faster model holds 97%+ with
zero fabrications, the whole problem is solved and nothing else here is
needed.

That the eval harness makes this a measurement rather than a gamble is
exactly what it was built for.

### 5. Per-order calls, concurrently — last resort

A 14-row table could extract in parallel. Lower wall-clock, more total
tokens, and one real hazard: **a model given a fragment produces spans in
the fragment's coordinate frame**, which is the bug 010 already cost you and
021 designed around. If you do this, pass the whole body with the segment's
offsets, never the fragment alone.

Do not reach for this until 1 through 4 are exhausted.

## And one thing that is not a latency fix but matters

**Stream the extraction into the page's trace.** Ten seconds of visible
progress reads completely differently from ten seconds of spinner, and the
progress plumbing from 021 already exists. It changes no number and
improves the thing people actually complain about.

## The guard on all of it

**Every change here is re-run against the corpus before it is kept.** A
latency fix that costs two points of accuracy is not a fix, and the baseline
is what says so. Record the before and after of both numbers — milliseconds
and accuracy — in the change.

## Acceptance

- Time to first token and generation time are measured separately and
  recorded, before any change.
- The committed baseline is unchanged, or improved, after every change kept.
- Zero fabrications holds throughout — asserted after each lever, not only
  at the end.
- Provenance spans still verify under CM-4 if their derivation moves to code.
- A fixture where the model omits a field yields `Unresolved` for it, and a
  test proves absence is never read as anything else.
- The trace reports extraction time per run, so a regression is visible
  rather than discovered.
- Total capture time for the 14-row fixture, with 023's lookups included,
  fits the budget with margin — this is the number the change exists for.

## Out of scope

Changing what the capture model holds. Any accuracy trade accepted without
a corpus run behind it.
