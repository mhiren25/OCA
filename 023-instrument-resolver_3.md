<!-- draft proposal · import with /opsx:new 023-instrument-resolver then /opsx:ff
     spec: enrichment
     after: 005 (the registry this registers with) -->

# 023-instrument-resolver

## Why

**The Draft Order service will not accept an order without an ISIN.** So
this is not enrichment that improves a draft — without it there is no draft.
Every order the agent captures today is unfileable.

That makes the resolution rate the ceiling on everything else this agent
does, and it changes what an unresolved instrument means.

## An unresolved instrument blocks the draft

011 says incomplete drafts are a supported outcome, and for quantity that
holds — `orderQty` unset still files. **For the instrument it does not.** A
line whose ISIN does not resolve produces no `OrderRequest` at all.

So review items split into two kinds, and the page must show the difference:

- **advisory** — the draft exists and something wants checking. A defaulted
  time in force, a disagreement between two sources.
- **blocking** — no draft could be built. The instrument did not resolve, or
  no listing permits the side.

A blocking item renders with `chip--invalid` and `tag-invalid`, which the
stylesheet already carries for 003's findings. It is the same category of
thing: *this cannot proceed as captured*.

The capture still succeeds and the other lines in the email are unaffected.
What the response carries for a blocked line is the captured order, the
reason, and the candidates — not a half-built payload.

### Which makes the review item the fallback path, not a diagnostic

This is where the never-pick rule earns its keep, and where it costs
something real: refusing to choose between two listings now means no draft
for that line, and a human doing it by hand.

It still holds. **A wrong ISIN produces a draft for a real, wrong security
that reads as correct to a reviewer** — a silent error against a tradable
instrument. No draft is visible; a wrong draft is not. And the manual
fallback is exactly what happens for every order today, so the worst case is
the status quo for that line.

But it raises the bar on the review item. It is not a note explaining a
failure, it is **the interface for the path a human now has to take**, so it
carries the candidates with their market, currency, ISIN and flags, laid out
so the choice takes seconds. A reviewer who has to go back to RDMSearch
themselves has been given nothing.

### The number that decides phase one

**Resolution rate — the share of captured orders whose ISIN resolves to
exactly one listing — bounds the clean-draft rate**, and nothing else in the
project can lift it above that ceiling.

Measure it on the existing corpus before building the rest: run RDMSearch
for every instrument in the fixtures and count how often the ladder lands on
one listing, with and without a client-stated currency. It is an hour's work
against data you already have, and it tells you what fraction of real orders
phase one can actually file.

## Plain client, not MCP

**An async SOAP client in `enrichment/`, not an MCP server.**

MCP earns its complexity when a *model* discovers tools and decides when to
call them. Here orchestration code calls this on a key the capture step
already produced. MCP would add a protocol hop, a deployment unit to run and
monitor, and a second home for the technical token, for no capability this
needs.

Revisit only if a later agent needs a model to drive the search itself. That
would be a wrapper around this client, not a replacement.

## The call

`searchListings_1_0`, one call per instrument.

| element | value | source |
|---|---|---|
| `caller` | `ocaAgent` | config |
| `orderEntrySystem` | `AAA` | config |
| `bookingDestination` | `p` | config — **semantics unknown, pinned until someone can say what it selects** |
| `request/collapse` | `true` | always |
| `request/securityId` | the identifier | from capture |
| `maxNumResults` | `10` | config |

Endpoint per environment, in the property file. Nothing above is compiled in.

`bookingDestination` is hardcoded because nobody currently knows what it
does. That is fine for now and worth a line in the config comment, because a
pinned value whose meaning is unknown is a thing that silently becomes wrong
when the service changes and nobody notices.

### Which identifier, and how many calls

**Ticker, then ISIN, then name** — strongest first, as the service responds
best to the most specific.

**One query per instrument.** Issue the strongest identifier capture holds.
Only if it returns nothing, fall back to the next, and cap the chain at two
attempts. The budget rules this: a 14-row table at two calls each is 28
round trips.

Note that `collapse=true` does **not** guarantee a single result — the
sample response collapses and still returns several listings for one ISIN,
because currency lines are distinct listings. Nothing downstream may assume
one row.

## The selection ladder

Candidates are narrowed by deterministic rules, in this order, and the
terminal state is honest when they do not narrow to one.

**1. Hard filter — the currency or market the client stated.**

Where the client named a currency or a venue, keep only listings matching
it. *"Buy 10,000 DBS in SGD"*, *"sell the LON line"* — these are their own
words, and a listing that contradicts them is not a candidate, however
canonical it looks.

This is the strongest signal in the ladder and it does most of the work on
the ambiguous cases: the sample response's GBP and USD listings of the same
ISIN separate immediately if the client said either currency.

`instrument.stated_currency` and `instrument.stated_venue` both survived
018 and are in the committed schema — confirmed 2026-10-17.

**What is not yet known is how often they are populated.** Being in the
schema and being `Mapped` on a real email are different things, and if
clients rarely state a currency or a venue, the strongest filter in this
ladder rarely fires. Count it in the same pass as the resolution-rate
measurement below: how many captured orders have either field Mapped.

**2. Hard filter — the direction is permitted.**
An IN order (`BUY` or `SUBSCRIBE`, per 025) needs `buyAllowed`; an OUT order
(`SELL` or `REDEEM`) needs `sellAllowed`.

**This is the only tradability filter.** It is safe because the listing
states a fact with no judgement in it: you cannot buy this. Segment and
prepayment are not filters — see below.

One check does not need a table. Build it plainly; make it a table when
there is a second rule that genuinely belongs beside it.

**3. Preference — the account's currency and market.**
Where the account resolver has supplied them, prefer listings matching the
account's currency, then its market.

A preference, not a filter: a client can trade a foreign listing in an SGD
account and let the FX settle, so a mismatch is not disqualifying. But when
two listings differ only by currency and the account is an SGD account, the
SGD line is the one they mean.

**This step is skipped when there is no account resolver yet**, or when it
returned nothing. The ladder still runs; it falls through to step 4 more
often and produces more review items. That is a degraded outcome, not a
wrong one, so **this change does not wait for the account resolver** — it
gets better when that lands.

An ipid supplied in the request is an identifier, not a currency. Knowing
the account's currency and market means a call to the account master, which
is its own resolver and its own change.

**4. Preference — `ubsMainMarket`, last.**
Only when nothing above has separated the candidates.

**5. Exactly one survivor → resolved.** Record the ISIN, the listing's
market and currency, the identifier used, what the service matched on
(`securityIdSource`), and the timestamp, as the field's provenance.

**6. Anything else → Unresolved, plus a review item.** Zero survivors or
several. Never pick.

### Why `ubsMainMarket` is last

It is the firm's canonical listing, not this client's. Main market `CH` means
nothing to a client holding the `SG` line and selling from an SGD account —
applying it ahead of the account would pick a listing the client does not
trade and has nothing in, and it would do so silently, because one survivor
resolves without comment.

So it ranks below both the client's own words and their account. It is the
answer to *"nothing here distinguishes these, which would the firm use"*,
which is the right question only once the better ones have been asked.

What keeps it legitimate at all is that it is **a fact the data supplies**,
not an inference drawn from the email. Code may apply a deterministic
tie-break the data provides; it may not invent one. A model choosing between
a GBP line and a USD line is inventing one, because what decides it is the
client's mandate, not anything in the text.

**And it often does not fire.** Both listings in the sample response have
`ubsMainMarket = false`. When the ladder runs out, step 6 is the answer —
**never "take the first row"**, which is the whole failure mode wearing a
different hat.

### Which means instrument now depends on account

Step 3 needs the account's currency and market, so the account resolver must
run first. 005 declares `depends_on = ()` for instrument, and that is a
fourth amendment it needs — this is exactly what its dependency machinery is
for.

**Positions are deliberately not consulted here.** The client's holding would
settle the SG-versus-CH case even more directly, but the positions service is
called only for sell-all by an earlier decision, and calling it for every
sell to disambiguate a listing would both reverse that and add a round trip
to the budget. The account's currency answers the same question for the same
cases, without the call. If it turns out not to be enough, the review item
carries the candidates until someone decides positions are worth the cost.

## Side permission is a filter first, a finding second

You said buy against `buyAllowed = false` should be an error. I would make it
narrower, in two ways.

**It filters before it fails.** `buyAllowed` is a property of *a listing*,
not of the instrument. Another listing of the same security may permit it,
so the restriction belongs in the ladder, where it often does useful work by
eliminating candidates.

**When it empties the set, it is a finding on that draft, not an error on the
request.** The capture still succeeds and the draft is still produced, with
the instrument unresolved and a blocking review item: *the client asked to
buy X; no listing found permits buying it.*

Failing the request instead would mean a reviewer sees nothing for that line
and has to go back to the email to find out why — and in a 14-row table, one
restricted instrument would take the other thirteen with it. The client asked
for something that cannot be done, and the person who needs to know that is
the human, in the draft, not a log.

**When a filter empties the candidate set, say which one did it.** Re-apply
the filters one at a time to find the first that reduced it to zero, and put
that in the review item. "No GBP listing" and "no listing permits buying" are
different conversations with the client, and the difference costs one extra
pass over a list of at most ten rows.

## Why segment is not a filter

Funds execute on both primary and secondary markets, so there is no reliable
rule mapping an order to a segment. An earlier draft of this proposal
filtered on `primary` / `secondary`. That was wrong, and the reason is worth
keeping written down:

**A filter that is wrong does not produce ambiguity — it produces a
confident wrong answer.** If a bad segment rule eliminates one of two
listings, the other resolves silently, and the draft names a real instrument
on the wrong line with nothing to indicate a choice was ever made. A review
item would at least have been visible.

So an uncertain rule costs more as a filter than it saves. `buyAllowed` /
`sellAllowed` is safe because the listing states a fact with no judgement in
it. Segment is an inference about booking mechanics from flags whose
operational meaning this agent does not own.

**It is not a tie-break either**, for the same reason: a tie-break only
fires when candidates are already ambiguous, and the alternative in that
state is asking the human, which is the better answer when the rule is not
trusted.

**What the flags do instead: they appear in the review item.** When a human
has to choose between listings, showing which is primary and which is
secondary is useful information. Putting the data where a person uses it,
rather than where code acts on it, costs nothing and risks nothing.

The same holds for `prepayment` while nobody can say where the order's
prepayment attribute comes from. If it is an account or mandate property,
the agent cannot see it and the check belongs to the validation service at
submit. Show the flag, do not act on it.

## What 025 is still needed for

`SUBSCRIBE` and `REDEEM` earn their place in the enum without any segment
filter:

- **Direction.** A subscribe is a buy-side action, so the `buyAllowed`
  check reads direction rather than `side` directly. Without the enum, a
  subscription would have to be captured as `BUY` and the client's actual
  word would be lost.
- **Capture records what the client said** — the two-schema principle, and
  the reviewer sees the real instruction.
- **The mapper needs it** to produce the right `OrderRequest`.

**025 lands before this change.** The information exists only in the email,
and nothing here reconstructs it once capture has flattened it.

## Prepayment, and where a check belongs

The rule is clear — a prepayment order against a listing with `prepayment =
false` fails. What is not clear is **where the order's prepayment attribute
comes from.** It does not sound like something a client writes in an email;
it sounds like a property of the fund, the account, or the mandate.

That distinction decides whether this check belongs here at all:

- **If the resolver can see everything the check needs** — the captured
  order plus the listing — it belongs in the ladder, because catching it
  before a human reads the draft is worth something.
- **If it needs data the agent does not have** — an account attribute, a
  mandate flag — then it belongs to the validation service that already runs
  when a draft is submitted from the GUI. That control exists, it sits closer
  to the moment of action, and it has the better view.

Re-implementing someone else's check with worse information is the thing to
avoid. Confirm the source before wiring it; if it turns out to be an account
property, drop the row from the table and let validation keep it.

## SOAP specifics that will bite

**`securityId` comes from a client email**, so hostile text goes into an XML
document. Never concatenate — template with proper escaping or use a real
SOAP client, and test an instrument name containing `<`, `&` and `]]>`.

**Parse with entity resolution and network access disabled.** A service you
trust still returns a document you did not write.

**A SOAP fault arrives with HTTP 200.** Checking the status is not checking
for an error, and a fault is not an empty result: a fault means *ask again*,
an empty result means *not found*. The review item should say which.

**A full result set may be truncated.** If the response returns exactly
`maxNumResults` listings, the candidate set is possibly incomplete, and a
filter that narrows it to one may have narrowed a set that was already cut
off. Record the truncation on the resolved value, so a surprising resolution
can be explained later.

**Budget the calls, and the budget is tighter than it looks.** A measured
run shows `extract` at **10.1 seconds**. Against a ~40-second window that
leaves roughly 30 seconds for everything else, so fourteen serial lookups do
not fit and concurrency is a requirement rather than a tuning option.

Bounded concurrency across an email's instruments, a hard per-call timeout,
and a cap on lookups per email. Past the cap the rest stay Unresolved with
review items — a slow lookup degrades the draft, it never fails the capture.

## Verify locally first

| profile | where | endpoint | auth |
|---|---|---|---|
| `direct` | local dev | the service | none |
| `gateway` | Azure | API gateway | technical token |

One client, profile from config. **Prove `direct` before writing `gateway`**
— it separates "is my envelope right" from "is my auth right", and debugging
both at once is what costs days.

## Cassettes and caching

Record/replay through the same machinery as the LLM provider, so eval runs
are offline and deterministic and a service outage never reads as an
accuracy regression.

Record only against corpus emails, which are redacted. A cassette of a live
UAT lookup is a committed file of real client instrument interest.

In-memory cache keyed on the normalised query, short TTL, **never to disk** —
012 persists nothing, and a query built from a client's email is client data.

## Four amendments 005 needs first

1. **`mcp_tool` bakes the transport into the ABC** — it should name the
   service and let config pick the client.
2. **The instrument `reads` list is stale** — it names `instrument.raw_text`
   and `instrument.form`, which 018 replaced with the three tri-state fields.
3. **`reasoning_required = True` for instrument** contradicts the ladder
   above. Set it False, or replace the flag with the ambiguity policy, which
   is the same for every resolver: narrow deterministically, then surface.
4. **`depends_on = ()` for instrument is wrong** — it depends on `account`,
   whose currency and market feed step 3.

## Acceptance

- A real `direct` call from a dev machine, no credentials, returns listings
  for a known instrument. First thing that passes.
- Config supplies endpoint, `caller`, `orderEntrySystem`, `bookingDestination`
  and `maxNumResults`; none appears in code.
- Each ladder step is a unit test with a hand-built candidate list.
- **Two listings differing only by currency, with no stated currency and
  `ubsMainMarket` false on both, leave the field Unresolved and produce one
  review item naming both.** This is the sample response, and the central
  claim of this proposal.
- A stated currency reduces that pair to one, which resolves.
- A stated venue reduces a multi-market set to one, which resolves.
- **With `ubsMainMarket = true` on the CH listing and an SGD account, the SG
  listing is chosen.** The account outranks the firm's main market —
  asserted, because getting this backwards resolves silently to a listing
  the client does not trade.
- An account currency matching no listing does not eliminate any candidate;
  it is a preference, not a filter.
- A client-stated currency matching no listing *does* empty the set, and the
  review item names that filter.
- A buy where every listing has `buyAllowed = false` produces **no payload
  for that line**, a blocking review item naming the reason, and no effect
  on the other orders in the email.
- A blocked line is distinguishable in the response from a draft carrying
  advisory items — one cannot be filed, the other can.
- A blocking review item lists each candidate's ISIN, market, currency and
  tradability flags, sufficient for a human to choose without re-querying
  the service.
- Resolution rate across the corpus is measured and recorded in the change,
  with and without a client-stated currency.
- A review item from an emptied candidate set names the filter that emptied it.
- **No candidate is ever eliminated by `primary`, `secondary` or
  `prepayment`** — asserted, because this is the constraint most likely to
  be "improved" back in by someone who thinks a filter is missing.
- A review item listing candidates shows each one's segment and prepayment
  flags.
- A `SUBSCRIBE` order is checked against `buyAllowed`, a `REDEEM` against
  `sellAllowed`.
- A ticker query returning nothing falls back once and no further.
- A response of exactly `maxNumResults` listings marks the result truncated.
- A SOAP fault is distinguished from an empty result.
- `securityId` containing `<`, `&` and `]]>` produces a well-formed request;
  a response with an external entity reference resolves nothing and touches
  no network.
- The 14-row fixture completes inside the capture budget, with lookup count
  and total lookup time in the trace.
- Eval runs make no network call.
- `gateway` selected by config alone, no code change.

## The other two resolvers

This proposal designs one of the three in 005, deliberately.

**Account** — needed for step 3, and the reason that step degrades
gracefully rather than blocking. Its own change: a call to the account
master returning the account's currency and market, plus the ipid matching
rule 012 already specifies. Build it next; this one is better with it and
correct without it.

**Position** — genuinely deferrable. It affects exactly one case, sell-all
with no figure stated, and 011 leaves that unset with a review item today,
which is a correct output. It is also a keyed lookup with one answer, so it
is a small change once account and instrument both exist, which is what 005
already says by making it depend on both.

## Out of scope

The account and position resolvers, per above. Anything that lets a model
choose an identifier.
