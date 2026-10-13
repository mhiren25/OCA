<!-- draft proposal · import with /opsx:new 014-tester-corrections then /opsx:ff
     spec: corpus -->

# 014-tester-corrections

## Why

Labelling has one bottleneck and it is a person. Meanwhile automated and
manual testing will put domain experts in front of real drafts, forming
exactly the judgement the corpus is short of, and currently throwing it away
when they close the tab.

A dev-only endpoint that accepts "this field was wrong, it should have been
X" turns testing effort into corpus growth and into a per-field correction
rate — which is the dev-time equivalent of production accuracy, with no
dependency on the Draft Order service.

## What changes

`src/trade_capture/api/` gains one endpoint, **dev only, failing closed in
production config**. An endpoint that accepts "here is what the answer should
have been" is not something to leave reachable in a live estate.

```
POST /v1/dev/expected/{job_id}
```

The body is **sparse** — only the fields the tester disagrees with:

```yaml
submitted_by: a.trader
role: trader | ops | qa
corrections:
  - field: lines[0].side
    expected: SELL
    note: "client wrote 'reduce', not a buy"
  - field: lines[2].account_ref
    expected: ~            # should have been Unresolved
notes: |
  Third order's account is genuinely ambiguous in the email.
```

Sparse because a tester restating twenty correct fields to flag three is
work nobody does twice. `expected: ~` means "this should have been blank" —
the agent over-reached — which is as important a signal as a wrong value.

Several corrections for one job are all kept: two testers disagreeing about
the same email is not a conflict to resolve by last-write-wins, it is the
single most valuable thing this endpoint can capture.

**A correction snapshots what it corrects.** Job results expire in 30
minutes; corrections are meant to last. A correction that merely references
a `job_id` becomes, within the hour, a note saying a field was wrong with no
record of which email or what the agent produced. So the stored correction
carries the source email and the agent's output alongside it — and inherits
their retention question rather than escaping it.

## What it produces

`scripts/correction_report.py` — per-field correction rate across everything
collected.

```
account_ref      corrected on 12 of 30 drafts   40%
instrument.isin   corrected on  3 of 30 drafts   10%
execution.expiry  corrected on  1 of 30 drafts    3%
```

That table is the thing that drives the next prompt change, and it comes
from real emails nobody has labelled, rated by people who know the domain.

Also worth reporting: corrections by role. A trader correcting a side is
authoritative. A QA engineer guessing at `targetStrategy` is a data point of
a different weight, and the two should not be averaged silently.

## Corrections are input, never labels

**Nothing written through this endpoint touches `corpus/`.** It lands in a
holding area and is promoted deliberately, through the ordinary route —
redact, scaffold, label, build — with the correction as *evidence*, not as
the answer.

Two reasons, and both have already cost this project time.

`corpus/` is CODEOWNERS-protected because an expectation that can be written
by whatever is currently failing is not an expectation. A tester is not an
agent, but an endpoint is an endpoint.

And **correction is a weaker form of labelling than labelling from scratch.**
A tester shown a draft and asked whether it is right is anchored by it, and
will wave through plausible-but-wrong values they would never have written
themselves. The same anchoring risk that keeps `scaffold_fixture.py` from
pre-filling a guess applies here, more strongly, because the guess is
presented as an answer.

So treat these as a lead, not a verdict. Where a correction turns into a
fixture, it is labelled independently and the correction is recorded in
`notes:` as what prompted it.

## Real client email on a UAT server

UAT runs on actual client email on a deployed server, so this store holds
real client data **with expert human annotation attached** — a richer
artifact than anything the agent produces alone. Three consequences.

**Retention needs its own answer and a named owner.** The 30-minute TTL on
job results was sized for a transient cache. Corrections persist by design,
and they now carry a copy of the email. That is a different conversation
from the one about job results, and it happens before the first correction
is stored, not after.

**Redaction happens on the server.** `redact.py` runs where the data is, so
what leaves UAT is already pseudonymised and the re-identification map never
moves. An egress of redacted material is a file copy; an egress of client
email is a governed process.

`redact.py` needs extending to take an email **and its corrections in one
pass, under one mapping**. A correction reading `expected: Tan Kok Hiong`
against a body where that name is now a pseudonym will fail
`build_fixture.py`, since values must appear verbatim in the source. That is
a safe failure rather than a silent one, but it is avoidable.

**Split what flows by what is in it.** The per-field correction rate is field
names and counts — no client data, moves freely, and is the number worth
watching week to week. Only the specific emails chosen to become fixtures
make the full journey, and they make it deliberately.

## Acceptance

- A correction against a known `job_id` is stored and retrievable.
- Two corrections for one job are both kept, with their submitters.
- The endpoint returns 404 in production configuration.
- `correction_report.py` produces the per-field table, broken down by role.
- No correction can reach `corpus/fixtures/` without a human running the
  normal build path.

## Out of scope

Automatic fixture creation. Production telemetry. Anything that reads the
submitted state back from the Draft Order service — that is the real
production signal and a separate conversation with that team.
