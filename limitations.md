# Limitations

What this agent deliberately does not do, and what its numbers do not mean.

These are **not** gaps. `docs/guardrails.md` lists gaps — things intended to
be closed. Everything here is by design, by scope, or by what the agent can
physically see. A limitation gets reconsidered when circumstances change,
not fixed in a sprint.

**Where a limitation leaves a real risk, it names who the control belongs
to.** A limitation with no owner is a gap nobody is holding.

> Written from the proposals, not verified against the code. Rows marked
> `CONFIRM` need checking; so does everything else, in the same pass as
> `guardrails.md`.

---

## What the agent does not do

**It never submits an order.** It returns draft payloads; a human files them
from the Draft Order screen. `lifecycleData.canSubmit` is on the deny-list
at both the mapper and the API boundary.

**It does not amend or cancel.** Capture only, and only from an inbound
instruction.

**It does not decide anything ambiguous.** Where several candidates survive
and nothing in the data distinguishes them, it surfaces them and stops. A
human chooses. *Owner: the reviewer.*

## What the numbers mean

**97.7% is field accuracy against the labelled corpus**, measured on
redacted emails, by replay. It is not a measurement of live traffic, and it
is not a claim about any individual draft.

**Zero fabrications is a corpus measurement.** The span check runs at
request time too, so it is not only retrospective — but "zero" describes the
corpus, not a guarantee about an email nobody has labelled.

**Every fixture is in the dev split.** There is no holdout, so the figure
carries the usual risk of a corpus that has been tuned against. `CONFIRM`

**Line recall is gated; line precision is not.** `CONFIRM`

**Resolution rate bounds the clean-draft rate.** However accurate
extraction is, a draft with no resolved ISIN cannot be filed, so instrument
resolution sets the ceiling on how much the agent actually delivers.

## Duplicate detection (029)

**Keyed on `Message-ID`, so it detects the same email processed twice —
nothing more.** Content is deliberately not inspected: two clients buying
the same security, or one client buying the same thing twice in a day, are
valid orders with near-identical text, and a check that flagged them would
be dismissed out of habit until it was worthless.

Consequences, all accepted:

- **A forwarded email is a different email** and is not detected.
- **Pasted text has no `Message-ID`** and cannot be checked at all. In
  production an attached `.eml` is checked; a paste is not.
- **Only captures that went through this agent are visible.** One trader
  capturing while another enters the order by hand, or the same instruction
  arriving twice by different channels, is invisible here.

*Owner: duplicate-order prevention across all channels belongs to the
validation service at submission, or to a firm-level control. This agent
reduces the risk it introduces; it does not own the risk.*

## Enrichment

**No account resolver in phase one.** The account's currency and market
therefore do not narrow instrument candidates, so more orders fall through
to the routing tie-break and more produce review items.

**The positions service is called only for sell-all.** Every other quantity
comes from what the client stated, and a stale figure is caught at
submission. *Owner: the validation service.*

**The resolver never chooses between different ISINs.** Where it cannot
narrow to one security, no draft is produced for that line. *Owner: the
reviewer.*

## Input

**The API accepts `.eml` and, after 028, text.** `.msg` is converted offline
by `scripts/msg2eml.py` and is not an API input.

**Attachments are not read.** An instruction that lives only in an attached
PDF or spreadsheet is not captured. `CONFIRM`

**The live region is what the sanitiser identifies.** An instruction placed
below a signature, or inside a quoted thread, is excluded by design — the
same mechanism that stops the agent acting on last week's orders.

## Deployment

**Nothing is persisted** beyond job results for their TTL and, after 029,
`Message-ID` hashes for their retention window. No email body, no extracted
values, no re-identification key.

**Logs carry no client data outside local development**, so a production
incident cannot be diagnosed by reading the prompt. Reproduction goes
through the corpus and cassettes instead.

**UAT runs on real client email.** Redaction happens on the server and the
re-identification map never leaves it. *Owner: retention for the correction
store needs a named person before the first correction is stored.*
