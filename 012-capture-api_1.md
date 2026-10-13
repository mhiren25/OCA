<!-- draft proposal · import with /opsx:new 012-capture-api then /opsx:ff
     spec: api -->

# 012-capture-api

## Why

Stakeholders have asked for API access: upload an `.eml`, get the Order
response back. This is also the shape the agent runs in for real — it is
called over REST — so building it now is the production entrypoint, not a
demo harness.

## What changes

`src/trade_capture/api/` — a small HTTP app behind the firm's API gateway.
A direct URL is kept for testing and **fails closed in production config**,
so the bypass cannot quietly become permanent.

```
POST /v1/capture            .eml + optional account ipids  ->  202 { job_id }
GET  /v1/capture/{job_id}                                  ->  200 result | 202 pending
GET  /                      the upload page
GET  /health
```

### Always asynchronous

The trigger always returns `202` and a job id — never a result, however fast
the model was.

A hybrid that returns orders when it finishes inside 40 seconds and an id
otherwise makes the response shape depend on model latency that day. Every
caller then handles both paths, and the fast path is the one that is never
properly tested because it cannot be reliably provoked. One contract is worth
more than one saved round trip.

The gateway times out at 60 seconds, so the *result* call may block up to
~40 and then answer `202 pending`. Long-polling (`?wait=30`) can be added
later without changing the contract.

### Input

- `email` — the `.eml`, required
- `account_ipids` — optional list of internal account identifiers, because
  not every email names an account
- `idempotency_key` — optional; a repeat returns the existing job id rather
  than running again. Duplicate drafts in a review queue are a real nuisance,
  and `externalOrderReference` is generated per run.

**The ipids are candidates, not an assertion.** Matching the client's words
to one of them is **code, not the model** — hand a model a vague reference
and a list of five accounts and it will pick one, which is the fabrication
class this project gates at zero, reappearing somewhere new. A reference that
matches none of the supplied ipids leaves the account unresolved and produces
a review item. It never guesses.

**The result carries three things:**

- `orders` — the `OrderRequest` payloads from 011, one per order line
- `capture` — the `CaptureEnvelope`, with provenance
- `review` — the items a human must act on (011's annotations)

`capture` is not debug output. It is *why* each value is what it is, and it
is what a reviewer needs. Returning only `orders` would ship the answer
without the evidence.

### The upload page

A static page served by the same app: file input, submit, render the result.

- The email on one side, the extracted orders on the other.
- Hovering a value highlights the words in the email that produced it.
- The raw `OrderRequest` JSON available but collapsed — stakeholders asked
  for the Order response and should be able to see it literally.
- `review` items shown prominently, and their count visible per draft.

This page is the reviewer UI in embryo, not throwaway. The provenance view is
what makes a draft checkable in seconds rather than re-read from scratch.

## Hard constraints

**The API never submits.** It returns payloads; it does not call the Draft
Order service. The deny-list runs at the API boundary as well as inside the
mapper — the boundary is what someone wires up next, and a check that lives
only one layer down is a check that gets bypassed by the next integration.

**The uploaded file is hostile input.** It arrives from a browser and goes
into an LLM prompt and then into a rendered page.

- Cap the upload size; reject what exceeds it rather than truncating.
- A `.eml` that fails to parse is a 400 with a plain message, never a crash
  and never a partial capture.
- **Escape everything from the email before it reaches the page.** The
  provenance view renders attacker-controlled text by design. Client email
  containing markup is the obvious XSS, and the file name is not a path.
- The prompt frames the body as untrusted data, never as instructions.

**Nothing is persisted.** No uploaded email is written to disk, no response
is stored. The content is client data and this is a dev environment. A
request leaves no trace except the log line below.

**Logs carry no client data.** Not the body, not the prompt, not the
extracted values. A log line is: request id, timestamp, order count, review
count, latency, outcome. Nothing a log aggregator should not see.

**Every request gets an id**, returned in the response and in the log line.
When this becomes one agent among several across a trade lifecycle, that id
is how a draft is tied back to the email it came from — and a correlation
scheme retrofitted later never covers what already happened.

### The OpenAPI contract

`api/openapi.yaml`, **generated from the code and committed** — the same
pattern as `capture.v1.schema.json`. Generated so it cannot drift from the
routes; committed so the gateway team has a stable file and a contract change
is visible in a diff.

The gateway needs more than paths, so the spec carries:

- the `bearerAuth` security scheme, applied to both operations
- `multipart/form-data` on the trigger, with the optional `account_ipids`
  and `idempotency_key` fields
- **202 with a `Location` header** pointing at the result endpoint — the
  conventional way to express this async shape
- every error response the caller can see: 400, 401, 404, 202-pending
- stable `operationId`s, which gateways use for routing and client
  generation

**Fully resolved, no external `$ref`s.** The capture envelope schema is large
and nested, and it is tempting to reference `corpus/schema/capture.v1.schema.json`
rather than inline it. Most gateways cannot resolve an external reference at
import time. Self-contained file, even though it is bigger.

**Confirm which OpenAPI version the gateway accepts before generating.** 3.1
and 3.0 differ in how they express schemas, recent FastAPI emits 3.1 by
default, and a number of gateways still only take 3.0. Finding that out at
import time costs a day.

Acceptance is not that the file validates — it is that **the gateway team can
import it**. Get that confirmed while the change is still open.

### Authentication

JWT; the CN is verified against an allow-list and anything else gets a 401.
Standard for the estate, and the gateway fronts it in production.

### Result storage — client data at rest

A job's result holds the capture envelope: client names, account references,
order details, and holdings once enrichment lands. Keeping it for 30 minutes
is a data-at-rest question, not an implementation detail, and the answer is
the same whether it lives in a database or a file.

v1 is in-process, single instance, 30-minute TTL. A restart loses every
outstanding id, so an unknown id answers **"expired or unknown"** rather than
implying it was never valid — otherwise a routine deploy reads as a bug.

Multi-instance behind the gateway needs shared storage. A database is the
better fit — encryption at rest, atomic writes and a queryable view of what
has not expired all come free. Where provisioning one is the longer road, a
shared NFS mount is acceptable **subject to four rules**:

1. Write a temp file and `rename` it into place. Rename is atomic within a
   filesystem; a plain write is not, and a reader will otherwise eventually
   get half a document.
2. Write once, never update. NFS locking is unreliable; write-once plus
   atomic rename means no lock is needed.
3. **Monitor the cleanup job, not just schedule it.** A database makes stale
   rows queryable. A directory silently accumulating client data for months
   does not. Alert on oldest-file age.
4. Mode 0600, a dedicated directory, and the mount's encryption and
   root-squash settings confirmed with its owner.

Check attribute caching between instances before trusting it — one instance
not immediately seeing another's file presents as random 404s on valid ids,
and only under load.

## Acceptance

- A `.eml` with three orders returns three payloads, the capture envelope,
  and the review items.
- A `.eml` with no order returns zero orders and says so — not an error.
- A malformed `.eml` returns 400 with a readable message.
- An email whose body contains `<script>` renders harmlessly on the page.
- A payload carrying a denied field never leaves the API; the test asserts at
  the HTTP boundary, not at the mapper.
- No log line emitted by a successful request contains text from the email.
- The page, opened in a browser, takes a file and shows orders with
  provenance highlighting.
- `api/openapi.yaml` regenerates from the code, is self-contained, and the
  gateway team has imported it successfully.

## Out of scope

Submission. Enrichment. Persistence or history. Multi-user anything.
Deterministic validators (003) — which should land before this is reachable
by anyone beyond a demo.

## After this lands

Measure the **clean-draft rate** on the corpus: the share of emails
producing a draft with zero review items. That is the number that decides
whether a trader uses this, and it is not the same as field accuracy.

Consider also what the review count tells you per email shape. A single-line
order a trader fills in fifteen seconds and a fourteen-row table they fill in
five minutes are different products, and the value is not evenly spread
between them.
