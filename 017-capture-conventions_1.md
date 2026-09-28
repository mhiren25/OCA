<!-- draft proposal · import with /opsx:new 017-capture-conventions then /opsx:ff
     spec: capture-model, extraction, corpus -->

# 017-capture-conventions

## Why

The first full eval run failed its gate with 65 fabrications. A manual check
of every one against its source email found **62 present verbatim and 3
not**:

- `0012-fw-order` lines 0–13 produced `ENR GY EQUITY`, `GOOGL US EQUITY`,
  `EVR US EQUITY` and eleven more. Those are the Ticker column of that email,
  read correctly row by row.
- `execution.expiry='Day Order'` — `0005`'s table reads `Market Market Day
  Order` in every row; `0006` says *"This is day order"*; `0007` says *"Order
  is gtc"*.
- `trade_date='today'`, `strategy='market open'`, `stated_venue='Japan'`,
  `account_ref='our account with Priscilla'` — all the client's own words.

`0010`'s `account_ref = "portfolio 4"` was initially read as a hallucination
on the grounds that the email only says `portfolio 2`. It does not: order 2
reads *"in portfolio 4"*, order 3 reads *"in portfolio 2"*, and the model
placed each on its own line correctly.

**No value in the run was invented.** Every one of the 65 was in the email.
What failed was the corpus's account of what should have been captured, and
the reporting format for values the model normalised.

`provenance_failures=0` on the same run, so every one of those values carries
a span that verifies against the body. **A value whose provenance verifies
came from the email.** It cannot be a fabrication, whatever the label says.

So the run did not measure the model at all. It measured three conventions
nobody had written down. A zero-tolerance gate whose definition is loose
fires on everything, and a gate that fires on everything is read as noise —
which is how a real fabrication would have been missed if there had been one.

Three separate confident claims were made during this analysis about what a
given email did or did not contain. Two were wrong, and each was corrected
only by opening the email. That is the argument for `LABEL_DISAGREEMENT`
being computed from verified spans in code rather than established by review:
the check does not get tired, and it does not grep for the wrong string.

This change writes the conventions down so the gate means what it says.

## Decision 1 — instrument identifiers are independent fields

`InstrumentRef` currently holds a `form` plus a primary `raw_text`, with
`also_name` / `also_ticker` / `also_isin` for whatever else the client gave.
That makes the slot a value lands in depend on what *else* is present: a
ticker is `raw_text` when it is the only identifier and `also_ticker` when an
ISIN accompanies it. The extractor and `build_fixture.py` resolved that
ambiguity differently, and 39 "fabrications" followed.

**Replace it with three independent tri-state fields:**

```
instrument.name       Mapped if the client wrote a name
instrument.ticker     Mapped if the client wrote a ticker
instrument.isin       Mapped if the client wrote an ISIN
```

No primary, no `also_`, no `form`. Each field is Mapped when the client
stated that identifier and Unresolved when they did not — a rule with no
dependency on any other field, so there is nothing for two implementations to
disagree about. Enrichment applies its own preference order (ISIN, then
ticker, then name) when it resolves; that is a resolver concern, not a
capture one.

`instrument.resolved`, `stated_currency` and `stated_venue` are unchanged.

## Decision 2 — the tri-state is about what the client SAID

The three states have been used inconsistently because their definitions were
never written in one place. They are:

| state | meaning |
|---|---|
| **Mapped** | The client said this. `raw_text` holds their words. |
| **Unmapped** | The client said something this schema cannot hold. |
| **Unresolved** | The client said nothing about this field. |

**Unresolved means absent, never "present but hard to interpret."**

So `trade_date: "today"` is Mapped, with `raw_text="today"`. So is
`account_ref: "portfolio 4"`, `strategy: "market open"`, `horizon: "first
hour"`. Turning "today" into a date, or "portfolio 4" into an account number,
is resolution — the same job the instrument resolver does, subject to the
same rule that a value the client did not give is never invented.

This follows from the architecture rather than adding to it: capture records
what the client said, enrichment records what the systems answered, and the
two never overwrite each other. A capture layer that discards "today" because
it is not yet a date has thrown away the client's instruction.

## Decision 3 — `raw_text` is quoted, `value` is normalised

A manual check of all 65 flagged fabrications found 62 present verbatim in
their emails and 3 not. Two of those 3 are the same case:

> `0007`, `0008` — `execution.order_type = "LIMIT"`, from *"at yen1920 or
> better"*. The word "limit" appears nowhere in either email.

That is a correct reading. A dealer would call it a limit order too. But the
model reported its *conclusion* where the schema asks for the client's
*words*, so the value carries no span and is indistinguishable from an
invention.

The fix is not to stop the model normalising — `side: "BUY"` from "buy" is
the same operation and is wanted. It is to keep the two apart:

- **`raw_text` is always the client's words, verbatim, and must locate in the
  body.** *"at yen1920 or better"*.
- **`value` is the normalised form.** `LIMIT`.

Prompt v2 states this for every field. A field whose `raw_text` does not
appear in the body is the definition of a fabrication, and with this rule
that test becomes exact rather than approximate.

The related principle still holds and belongs in the prompt: **never infer a
value from a convention, a default, or what is usual.** It was not, as
previously written here, the cause of the expiry results — those were stated
in the emails — but a business rule such as "default TIF to DAY" belongs in
the mapper where it is visible and testable, never inside extraction.

## Decision 4 — a verified span is not a fabrication

`evals/scoring.py` classifies expected-Unresolved / actual-Mapped as
FABRICATION. That is right when the value was invented and wrong when it was
quoted from the email.

Add `Outcome.LABEL_DISAGREEMENT`: expected Unresolved, actual Mapped, **and
the actual value's provenance span verifies against the body**. Report it
separately and exclude it from the zero-fabrication gate. Fabrication keeps
its meaning — a value with no source in the text — and stays gated at zero.

This is the distinction that makes the gate trustworthy. Without it, every
convention disagreement reads as the most serious failure class the system
has, and people learn to discount the number.

`scoring.py` is CODEOWNERS-protected, so this part is a human edit and not in
this change's scope. It is recorded here because the other three decisions do
not make sense without it.

## Also in scope

`USD3mil` was rejected by the locator with *"located text is not a positive
number"*, on a line whose quantity is a cash amount. `CashAmount` already
exists in the `Quantity` union — the locator is simply parsing every quantity
as a count. Route a cash-amount quantity to `CashAmount` rather than failing.

## What changes

- `domain/capture.py` — `InstrumentRef` gains `name` / `ticker` / `isin`,
  loses `form`, `raw_text` and the three `also_*` fields
- `extraction/prompts/v2.py` — the tri-state definitions above verbatim, the
  no-defaults rule, and the new instrument fields
- `extraction/extractor.py` — cash-amount quantities map to `CashAmount`
- `scripts/build_fixture.py` — emit the three identifier fields
- `docs/corpus-spec.md` — the tri-state table, as the labelling rule
- `corpus/schema/capture.v1.schema.json` — regenerated

## Acceptance

- Every fixture rebuilds with `python scripts/build_fixture.py
  corpus/fixtures/` and validates against the regenerated schema.
- No fixture carries `form`, `raw_text` or an `also_*` field on an
  instrument.
- A fixture whose email states a ticker and an ISIN has both fields Mapped,
  independently.
- Prompt v2 contains no default, convention or "usually" anywhere.
- An email stating no expiry produces `execution.expiry` Unresolved.
- `USD3mil` produces a `CashAmount`, not a locate failure.

## Not in this change

The mapper's TIF default (011). The `scoring.py` edit (human, protected).
Relabelling (human, `corpus/` is protected).

## Sequencing

The fixtures must be relabelled for Decision 2 — every `trade_date: today`,
`account_ref: portfolio 4` and similar becomes a filled field in
`label.yaml` rather than a blank. That is human work on protected files and
should happen after the schema lands, so the rebuild and the relabel are one
pass rather than two.
