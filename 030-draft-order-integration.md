<!-- draft proposal · import with /opsx:new 030-draft-order-integration then /opsx:ff
     spec: mapping
     before: 029 — this changes what 029's identity layer attaches to -->

# 030-draft-order-integration

## Why

The real `OrderRequest` contract is now in hand, and it differs from what
011 assumed in ways that matter. At the same time the agent's job has grown:
it no longer hands a payload to someone else, it **creates the draft and
returns its id**.

Three things follow — define what the agent supports, reconcile what is
already built against the real schema, and call the service.

## The invariant survives, and matters more

**The agent saves a draft. It never submits an order.** A draft still
requires a human to open it in the Draft Order screen and submit it, so the
human-in-the-loop property holds.

What changes is that 012's wording — *"it does not call the Draft Order
service"* — is now false, and the deny-list is load-bearing in a way it was
not before. `lifecycleData.canSubmit` and anything else that could cause a
draft to act on its own must be stripped **before the call leaves**, not
merely absent from the payload we would have returned.

## Supported fields

| `OrderRequest` | source | notes |
|---|---|---|
| `side` | capture | `BUY`, `SELL`, **`FSUBSCRIBE`**, `REDEEM` — 025 captures `SUBSCRIBE`; the mapper translates |
| `instrument.securityId` | 023 | the resolved ISIN |
| `instrument.securityIdSource` | fixed | `ISIN` |
| `currency` | 023 / capture | from the resolved listing, or stated by the client |
| `exDestination` | 023 | the resolved listing's market |
| `ordType` | capture | `MARKET`, `LIMIT` |
| `price` | capture | only when the client stated a limit |
| `orderQtyData.orderQty` | capture | |
| `quantityType` | derived | `QUANTITY`, `AMOUNT`, `NOMINAL`, `FACE_AMOUNT` |
| `timeInForce` | capture | `DAY` default |
| `expireDate` | capture | **only when `GTD`** |
| `effectiveDate` | request | only when supplied |
| `targetStrategy` | capture | when the client stated one |
| `strategyParameters` | capture | when the client stated them |
| `traderNote` | capture | the client's execution instruction, verbatim |
| `execInstrs` | **fixed** | always `[BEST_EXECUTION]` |
| `accounts` | **request** | from the supplied ipids; `null` when not provided |
| `flowFeatureSet` | **fixed** | marks the draft as agent-originated |
| `clOrdId` | generated | our id — see below |

**A field the agent does not support is absent, never defaulted.** The same
rule as everywhere else: a value nobody asked for is a value nobody can
check.

### `parties` comes from config, with the sample values for now

The whole `parties` block goes in the property file, seeded from the
observed trace:

```json
[ { "partyId": "WMG-SOE", "partyIdSource": "PROPRIETARY",
    "partyRole": "ENTERING_SYSTEM" },
  { "partyId": "p", "partyRole": "CLEARING_FIRM",
    "partyIdQualifier": "TOPAZ_BOOKING_DESTINATION" } ]
```

Two things to come back to, both recorded rather than solved:

**`ENTERING_SYSTEM: WMG-SOE` is someone else's identity.** Left as it is,
every agent-created order claims to have been entered by that system, and
nothing downstream can tell agent orders from theirs. That is the opposite
of what the marker is for.

So for now `flowFeatureSet` carries the agent marker, and **the open
question is whether Topaz will issue the agent its own `ENTERING_SYSTEM`
value.** If they do, that becomes the marker — it is a standard field other
systems already read — and `flowFeatureSet` can go. Until then, do not set
both to mean the same thing; two markers that can disagree is worse than
one.

**`"p"` is the same value hardcoded as `bookingDestination` in the RDMSearch
call (023).** Same concept, two places, neither understood. Make it **one
config value used by both**, so that when someone learns what it selects
there is a single thing to change.

Whichever marker wins, its value is the same: it tells anyone downstream
where a draft came from, and it makes the later comparison possible —
agent-created drafts against manual ones, on amendment rate, rejection rate,
time to submit. That is the adoption evidence this project will be asked
for, and it only exists if the marker is there from the first draft.

### `execInstrs` is fixed, `targetStrategy` is not

`execInstrs` is always `[BEST_EXECUTION]`. A client's execution preference —
*"work it over the day"*, *"at the close"* — is a **`targetStrategy`**
(`TWAP`, `ATCLOSE`, …), not an exec instruction. Keeping those separate
stops the client's words leaking into a field that is a fixed policy.

Put `BEST_EXECUTION` behind a named constant rather than a literal. It is a
business decision, and business decisions get revisited.

### Accounts come from the request, and they are typed

Phase one does not translate an account from the client's words.

But the trace shows `accounts` is **not a flat list of ipids** — each entry
is typed, and a single order carries more than one:

```json
[ { "accountId": "98001001A6LB…", "accountType": "BR" },
  { "accountId": "98002000A6LB…", "accountType": "PORTFOLIO" } ]
```

A banking relation and a portfolio, together. The caller supplies this
structure — id and type per entry — so the agent passes it through rather
than deriving anything. That is a change to 012's `account_ipids` field,
which took bare identifiers.

Absent accounts means the field is omitted and the draft carries a review
message.

## Generate the models; call it the same way as everything else

**The call goes through the same client pattern as RDMSearch and the LLM
provider.** One outbound pattern in this codebase, not two.

That is not a stylistic preference. **Cassettes** are the reason: every
outbound call is recorded and replayed so eval runs are offline and
deterministic, and a generated client sits outside that machinery. The
choice would be eval runs hitting the Draft Order service, or wrapping the
generated client — and a generated client plus a wrapper is more code than
generated models plus the client that already exists.

The same applies to everything else this change requires and a generated
client would not provide: the deny-list running before the request leaves,
correlation ids per capture, retaining the full response, partial success
across lines, 024's logging.

**Generate the types, though.** The spec is published, so request and
response models come from it rather than from reading it by eye — which
removes a class of error this change has already produced once, since
`SUBSCRIBE` against `FSUBSCRIBE` was a transcription mistake and there are a
dozen enums where another could hide.

Types and transport can differ here without inconsistency, because the
tooling does. OpenAPI generates clean Python models; WSDL does not, which is
why RDMSearch's types are hand-written. Take the free types where they are
free, and keep the single way of making calls either way.

Use whatever generator the estate standardises on if there is one — the
trace shows a `Java-SDK` user-agent, so a practice probably exists and
matching it costs nothing.

**Commit the generated models and mark them generated.** Two reasons:
build-time generation that fetches a spec over the network is a fragile step
in this estate, and committing means a spec change shows up as a diff, which
is exactly the visibility a contract deserves.

**Protect them the way `corpus/` is protected.** Generated code that gets
hand-edited stops matching the spec and says nothing about it — a silent
lie, and the agent's write restrictions should cover it for the same reason
they cover the baselines.

## Enums: fix them now, but not by matching theirs

Do it in this change. 025 already ships a value the service does not accept,
a wrong enum fails at the service rather than in tests — the slowest
feedback available — and once generation is in place the correction is
nearly free.

**The fix is not making the capture enums match the service's.** The
two-schema principle still holds: capture keeps `SUBSCRIBE` because that is
what the client wrote, and the service gets `FSUBSCRIBE` because that is
what it accepts. Changing capture to match the service would throw away the
client's words to save a lookup.

What needs to be complete is **the translation between them**, and with
generated enums as the target type it is checkable:

- every capture value maps to exactly one service value
- **an unmapped value raises rather than passing through** — a mapper that
  silently forwards something the service will reject has moved the failure
  from a test to production
- the table is exhaustive by test, not by inspection

That table is also where the next discrepancy will surface, so it is worth
having a single one rather than scattered conditionals.

## Four corrections to what is built

**`externalOrderReference` is `readOnly`.** 011 sets it to
`TCA-<ULID>-<line_index>`. The service generates it, so that must stop —
and **029's deterministic-reference layer has to move to `clOrdId`**, which
is writable and is where our generated id now goes.

**`clOrdId` is writable.** 011 says it is never set because the service
generates it. The opposite is true.

**There is no `execInstructions` field.** 011 describes a 256-character
free-text `execInstructions` that the service silently trims. No such field
exists in the contract — the free text is `traderNote`, and `execInstrs` is
the enum array. **Find out whether `traderNote` has a length limit**: the
original concern was sound even if aimed at the wrong field, and a service
that silently truncates a client's instruction is a defect nobody notices.

**`cashOrderQty` is `readOnly`.** The rendered schema makes this plain:
`OrderQtyData` exposes **`orderQty` and nothing else** as writable, while
the example still shows `faceValue` and `cashOrderQty` because they come
back populated.

So *"Buy USD 3,000,000"* cannot be sent as a cash quantity. One writable
number plus `quantityType` saying what it means — `AMOUNT` for cash,
`QUANTITY` for shares, `NOMINAL` or `FACE_AMOUNT` for the bond cases.

**Confirm it anyway.** It is the commonest shape in the corpus, the
inference is sound but it is still an inference, and getting it wrong means
the agent's most frequent order is silently a share count instead of a cash
amount — three million shares rather than three million dollars.

## Scope: create only

```
POST /order-requests  → createOrderRequest → OrderRequest
```

One call per order line. A line whose instrument did not resolve is not
sent at all — it has no ISIN and nothing to create.

**`saveOrderRequest` is deliberately out of this change** and lands as its
own, after the create path is proven against the real service.

### Verify this first: is a created request visible without the save?

`saveOrderRequest` is described as *"save order request as draft, this will
persist order request to continue later"*. If create alone does not put the
request where a trader can find it, then **this change validates the mapping
but delivers no user-visible feature**, and the save is not an optional
follow-up but a requirement.

Find out before anyone demonstrates it. Create one from a corpus fixture and
look for it in the Draft Order screen. The answer does not change what to
build here — it changes what can be claimed about it.

### Keeping the save non-conflicting

Adding it later is additive only if the seam is left open now:

- **Return the whole create response from the client**, not just the id.
  `validation.signature` and `lifecycleData` are unused today; discard them
  and the save change has to go back and re-plumb them.
- **Shape the agent's response for messages from the start** — an empty
  list today, populated by validation messages later. A response that gains
  a field is a contract change; one whose field gains contents is not.
- **Orchestrate as "create, then save" with save unimplemented**, rather
  than "create and return". The later change fills a branch instead of
  restructuring a flow.

### Create takes the whole order

Every field in the table above goes in this one call — `side`,
`orderQtyData`, `ordType`, `timeInForce`, `price`, all of it.

The trace reproduced above sends only `clOrdId`, `accounts`,
`contactInstruction`, `parties`, `instrument`, `exDestination`, `currency`
and `execInstrs`. That is one sample among several, and it is a **minimal**
order rather than evidence of a second call: only the instrument is
mandatory, so a request carrying little more than an instrument is valid.

Worth keeping as a test case for exactly that reason. It is a real example
of the rule this change depends on — **a field the capture did not fill is
absent, not defaulted** — produced by the service's own users rather than
invented here.

### The headers

Twenty of them, in three groups, and only the third is difficult.

| group | headers | source |
|---|---|---|
| **static** | `x-auth-mandator`, `ubs-topas-mandator`, `ubs-req-pckey`, `ubs-req-pcvalue`, `ubs-req-authsid`, `ubs-req-senderid`, `accept-language`, `user-agent` | config, seeded from the trace |
| **per request** | `ubs-topas-trace-id`, `ubs-topas-interaction-id` | generated per capture |
| **per user** | `remote-user`, `sso_logonid`, `x-auth-uids`, `x-auth-usertype`, `x-auth-strength`, `x-auth-location`, `x-auth-channel`, `x-auth-usersession` | **see below** |

The first group goes in the property file beside `parties` and the booking
destination. The second is generated and recorded alongside 024's request
id, so a draft in Topaz ties back to the email it came from without anyone
cross-referencing by timestamp.

### Whose identity does the agent present?

The third group identifies a **human** — a T-number, an authentication
strength, a channel, a location. The agent is not one, and this has to be
settled before the client is written because it changes the agent's own
inbound contract.

Two options:

**A service identity.** The agent has its own technical account and every
draft is entered by it. Simple, honest about what happened, and no
delegation.

**The caller's identity, propagated.** The agent presents the trader on
whose behalf it is acting, taken from the inbound request.

**`SearchDraftsRequest` probably decides it.** That schema filters drafts by
`users` — *"UBS t-number only"* — and by banking relation. If the Draft
Order screen lists drafts per user, then a draft created under a service
identity **is not in the trader's list**, and the agent has produced
something they cannot find. That is the same failure as the create-versus-
save question above, arriving by a different route.

So confirm how the screen lists drafts before choosing. If it is per-user,
propagation is required and three things follow:

- the agent's inbound contract must carry the caller's identity — 012
  verifies a CN from a JWT, so **check whether that yields a T-number**, and
  if not, what does
- the agent is then performing **delegation**, which in this estate is
  normally sanctioned explicitly rather than assumed. Ask whether the
  gateway does a token exchange, or whether a service-account-on-behalf-of
  pattern exists
- a capture arriving without a usable caller identity cannot create a draft,
  and must say so rather than falling back to a service identity

**One thing the trace shows that bears on this:** `authorisation` and
`x-auth-usersession` are both empty. Identity appears to be *asserted* by
the caller rather than proven to the service. That does not make
propagation wrong, but it does mean the controls are the agent's entitlement
to call the endpoint at all and the correctness of what it asserts — not a
check the service performs. Worth raising with them rather than relying on.

**Partial success is the case to design for.** Three lines, the second
fails: the first is saved, the third should still be attempted, and the
response must say exactly which succeeded and which did not. Failing the
whole capture because one line was rejected throws away work the trader can
use.

### `signature`, for when the save change comes

Answered by the trace, and recorded here so the next change does not have to
rediscover it: the create response carries `validation.signature` (`"0"` in
the observed call). The agent **echoes that value back on save** — it is an
acknowledgement token the service issues, not something the agent computes,
so nothing is forged and no override is manufactured.

The policy decision that belongs with it: when validation returns actual
messages, **save anyway and surface them**. A draft carrying warnings is
still useful — the trader opens it, sees what was flagged, decides. What
must not happen is the agent saving quietly while the messages reach nobody.

Capture the signature from the create response now even though nothing uses
it, per the seam above.

## What the agent returns

Per line: the `orderRequestId`, and the messages the user should check when
they open the draft — the agent's own review items, plus any validation
messages the service returned.

A URL later, once the Draft Order screen's deep-link format is known;
`orderRequestId` is enough to begin with.

This replaces the `orders` array of payloads in 012's result. `capture` and
its provenance stay, because the page still renders them.

## Acceptance

- A resolved line creates an order request, and the response carries its
  `orderRequestId`.
- **Only the instrument is required.** A line with nothing but a resolved
  ISIN creates successfully, and every field the capture did not fill is
  absent from the request rather than defaulted — asserted field by field.
- The full create response is retained internally, including
  `validation.signature` and `lifecycleData`, even though nothing reads
  them yet.
- The agent's response carries a messages list, empty in this change.
- No payload sets `externalOrderReference`, `orderRequestId`,
  `cashOrderQty` or `faceValue` — asserted, since all four are `readOnly`.
- `clOrdId` carries the agent's generated id.
- A captured `SUBSCRIBE` is sent as `FSUBSCRIBE`.
- `execInstrs` is `[BEST_EXECUTION]` on every draft, whatever the client
  wrote; a stated execution preference appears as `targetStrategy`, and the
  client's words appear in `traderNote` unmodified.
- `expireDate` is set only when `timeInForce` is `GTD`, and never otherwise.
- A cash-denominated instruction produces the confirmed quantity shape, not
  `cashOrderQty`.
- An unresolved instrument produces no call to the service.
- `flowFeatureSet` marks every draft the agent creates.
- Three lines where the second fails: two drafts saved, and the response
  names the failure.
- **The deny-list runs before the request leaves**, asserted at the HTTP
  client, not only in the mapper.
- No request sends `lifecycleData` — the service returns it with
  `canSubmit` and `canOverride`, and the agent never echoes it back.
- `ubs-topas-trace-id` and `ubs-topas-interaction-id` are generated per
  capture and appear in the agent's own trace and logs.
- `parties`, the booking destination and the static headers are read from
  config, not from code.
- Every header in the observed trace is sent, and a missing one fails the
  call rather than being silently omitted.
- A capture with no usable caller identity does not create a draft, and the
  response says why — **it never falls back to a service identity**, if
  propagation is the chosen model.
- Request and response types are generated from the published spec, and
  regenerating produces no diff against what is committed.
- **The call goes through the same client pattern as RDMSearch and the LLM
  provider**, and an eval run makes no network call to the Draft Order
  service — asserted, because that is what the single pattern is for.
- **Every capture enum value maps to exactly one service value, and an
  unmapped value raises** — asserted exhaustively, not by inspection.
- Generated files carry a do-not-edit marker and are covered by the agent's
  write restrictions.
- The booking destination is one config value, used by both the RDMSearch
  call and the `CLEARING_FIRM` party.

## Out of scope

**`saveOrderRequest`** — its own change, built on the seam above, once
create is proven and the save call's request shape has been observed.

Submitting. Amending or cancelling — `AmendOrderRequest` exists and is a
later conversation. Translating an account from the client's words; the
caller supplies accounts.
