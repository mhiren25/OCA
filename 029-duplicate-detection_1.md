<!-- draft proposal · import with /opsx:new 029-duplicate-detection then /opsx:ff
     spec: api -->

# 029-duplicate-detection

## Why

A trader captures the same client email twice and files both drafts. Two
orders reach the market for one instruction — a position the client did not
ask for, and unwinding it costs real money.

The agent does not submit, so it cannot prevent this alone. But it makes
producing a draft easy, which makes producing two easy, so it carries a
share of the control.

## The key is the email, not the content

An earlier draft of this proposal keyed on a hash of the live region. That
was wrong, and two ordinary cases show why:

- **Client A and Client B both buy Tesla.** Similar instructions, two valid
  orders.
- **Client A buys 10 in the morning and 10 more in the afternoon.** The
  second email's body can be byte-identical to the first. Two valid orders.

Content hashing flags both as duplicates. And a false positive here is not a
minor annoyance — **a control that fires on legitimate orders gets clicked
through**, and a trader trained to dismiss the warning dismisses the real
one too. A duplicate check that fires wrongly is worse than none.

So the question is not *have we seen these instructions before* — it is
**have we processed this email before**. The identity of an email is not its
text.

## Which identifier

**The RFC `Message-ID`** — `internetMessageId` in Graph — taken from the
`.eml` headers.

**Not Graph's `id`.** That is per-mailbox: the same email sitting in two
traders' mailboxes has two different Graph ids, and two traders each
capturing their own copy is exactly the duplicate worth catching. The
`Message-ID` is the same in both.

**No `Message-ID`, no check.** Pasted text (028) has none, and a malformed
header is possible. The capture proceeds and the result says the check could
not run, rather than implying it passed.

**A forward is a different email** and gets a new `Message-ID`, so it is not
caught. That is accepted deliberately: catching it would mean inspecting
content, which is the mechanism this proposal just rejected.

## `externalOrderReference` derives from the email, not a ULID

Today it is `TCA-<ULID>-<line_index>`, fresh per run. 011 calls it the
idempotency key, but **a random key provides no idempotency** — it dedupes
retries of one response and nothing else.

Derive it from `<message-id hash>-<line_index>` instead. The same email
captured twice then produces the same reference, so the Draft Order service
can recognise it at the submission boundary if it chooses to — and the
morning and afternoon Tesla orders, being different emails, carry different
references and both proceed.

Where there is no `Message-ID`, fall back to a ULID as today. No identity,
no idempotency; better to say so than to manufacture one.

**This asks nothing of the Draft Order service.** Given their own examples,
it should not dedupe on content, and it has no reason to reject two
references that differ. The reference simply becomes meaningful instead of
random, and whatever they do with it is theirs.

## What this does not solve, stated plainly

**The agent only sees what came through the agent.** One trader captures
while another enters the same order by hand; the client sends the
instruction twice as two emails; someone forwards and captures the forward.
None of those are visible here, and none of them should be solved by
guessing from content.

So this reduces the risk the agent introduces. It is not the firm's
duplicate-order control, and the worst outcome of building it would be
someone treating it as one.

**Worth asking whether the validation service already detects duplicates at
submission** — it runs when a draft is filed and sits closer to the moment
of action. If it does, the agent's job shrinks to not making things worse.

## Behaviour, scoped by environment

One config setting, `duplicate_check`, with three values:

| value | behaviour | where |
|---|---|---|
| `off` | no check, and the result says so | local dev; UAT while testers are exercising scenarios |
| `warn` | flag it, link to the earlier job, proceed | UAT when testing the control itself |
| `enforce` | flag it and require an explicit acknowledgement before the drafts are presented as fileable | **production, forced** |

**Config, not a request field.** The CID toggle is a request field because it
declares something about the input that only the uploader knows. Whether
duplicates are enforced is a *policy*, and policy belongs to whoever deploys
the environment. A per-request bypass is also exactly the parameter that
gets copied onto the gateway path for one urgent release and stays.

**Production refuses to start on anything but `enforce`** — the same shape
as payload logging, the CID toggle and the dev endpoint.

Keeping `warn` as a distinct value matters: it lets UAT exercise the real
detection path without blocking testers, so the control is proven somewhere
before production is the first place it ever fires.

### The direct route and the page are off in production only

One flag, `direct_access`, covering both — the page and the route that
serves it are the same thing, and nothing is gained by letting them differ.

| environment | `direct_access` |
|---|---|
| local dev, QA, UAT | enabled |
| **production** | **disabled** |

UAT keeps the page deliberately: that is where testers and domain experts
explore scenarios and correct values, which is what 014 is built around and
where the corpus grows. Production is the only place nobody uploads a file
by hand — the Draft Order screen calls the API through the gateway, and
there is no reason for a correction UI to exist there at all.

**Absent config means disabled.** Three environments then have to set it
explicitly, which is the right way round: forgetting it means a missing page
in UAT, noticed within minutes, rather than a live page in production,
noticed by whoever finds it.

Disabled means the page and the direct route both 404 — **asserted, not
assumed.** 012 specified this and it has never been tested, and this
conversation has twice turned up things that were specified and not built.

It also gives the duplicate bypass a second, independent control: with the
page absent in production, a misconfigured `duplicate_check` has no surface
to reach anyone through.

Warning rather than blocking in dev and UAT is not a compromise: re-running
the same email is the main activity of the testing phase, and 014's coverage
checklist exists to encourage it.

The warning says **when** the earlier capture happened and **by whom** —
*"you captured this twelve minutes ago"* and *"a colleague captured this
yesterday"* call for different responses.

## The store

### It needs one atomic operation, not two

The interface is a single method:

```
check_and_record(key) -> prior record | None
```

Atomic. Not `seen()` followed by `record()`, because between those two calls
is the race this control exists to prevent: two captures of the same email,
on two instances or from one double-click, both reading "not seen" and both
proceeding.

Putting atomicity in the interface means no caller can get it wrong, and it
is the only thing the backends genuinely have to agree on.

### This is **not** the same storage problem as the job store

012 allows NFS for job results under four rules, and that is sound: a job id
is unique, written once, never contended. **The duplicate key is contended
by definition** — the whole point is two writers racing for the same key —
and NFS locking is unreliable, which 012 says itself.

So they share an infrastructure question and not a set of guarantees. Do not
reuse the job store's mechanism here on the grounds that it already exists.

### Two properties, and the backend needs both

**Shared** — every pod reads the same data. Instance A sees an email;
instance B must know that when the same email arrives there.

**Atomic** — two pods racing on one key produce one winner. A double-click,
or two traders reacting to the same client email at the same moment.

Most storage gives one and not the other, and the one that is missing
decides whether the control works:

| option | shared | atomic | verdict |
|---|---|---|---|
| in-memory | ✗ | ✓ | tests only |
| SQLite on local disk | ✗ | ✓ | **local dev only** — never for pods |
| a file on NFS | ✓ | ✗ | **not suitable**: `O_CREAT\|O_EXCL` is not reliable over NFS, and the duplicate key is contended by definition |
| the firm's database | ✓ | ✓ | correct — unique constraint, or insert-on-conflict |
| **Azure Blob, conditional create** | ✓ | ✓ | correct, and usually the easiest to provision |
| Azure Table Storage | ✓ | ✓ | correct — insert returns 409 on an existing key |

### The operation is create-if-absent, and nothing more

That is the whole requirement, which is why so many things can serve it:

- SQL — `INSERT` against a unique key, caught on conflict
- Blob — `PUT` with `If-None-Match: *`, which returns 412 if it already
  exists. Blob name is the hash; **retention is a lifecycle policy**, so
  expiry needs no code at all
- Table — `Insert`, which returns 409 on a duplicate row key

No query language, no schema migration, no DBA. If provisioning a database
is the slow path in this estate, **blob storage gives the exact semantics
with far less paperwork**, and the same account can hold the job results
that 012 still needs to share across instances.

**Production with more than one instance requires a shared atomic backend
and refuses to start otherwise** — the same environment-scoped shape as the
CID toggle, the dev endpoint and payload logging. A safety control that
silently runs non-atomically is worse than one that is visibly absent.

Where none is available and multiple instances are required, the honest
outcome is that the check degrades and says so, not that it quietly becomes
best-effort.

### What is stored

**A hash of the `Message-ID`, never the ID itself.** A `Message-ID` carries
the sending domain and usually a timestamp, which makes it client metadata;
its hash does not, so the no-persistence property holds.

Alongside it: the capture timestamp and the principal, because the warning
has to say *when* and *by whom*. Nothing else.

Retention configurable, defaulting to one working day.

### Separately: the job store still needs fixing

012's multi-instance question is still open, and a poll landing on a
different instance than the capture still answers "expired or unknown" —
intermittent under a round-robin gateway and miserable to diagnose. That is
real and worth doing alongside this, but it is a different problem with
weaker requirements, and conflating them will push NFS's guarantees onto a
check that cannot accept them.

## Acceptance

- The same `.eml` captured twice is flagged; the second capture still
  produces drafts in dev and UAT, and requires acknowledgement in production.
- **Two emails with identical bodies and different `Message-ID`s are not
  flagged** — the morning and afternoon case, asserted directly, because
  this is the failure the earlier design had.
- Two different clients' emails are never flagged for similarity.
- An email with no `Message-ID` captures normally, and the result states
  that the check could not run.
- `externalOrderReference` is stable across two captures of the same email
  and differs between two emails with identical bodies.
- Only hashes are persisted — a test asserts no `Message-ID` and no body
  text reaches the store.
- **A poll served by a different instance than the capture returns the
  result**, not "expired or unknown" — asserted with two instances running.
- Entries expire on the configured window.
- **Two simultaneous captures of the same email produce exactly one "first"
  and one "duplicate"** — asserted with concurrent calls against each
  backend, because this is the case the control exists for and the one a
  non-atomic store gets wrong.
- **A capture on instance A is seen as a duplicate by instance B** —
  asserted with two processes against the shared backend, not one process
  twice. This is the requirement; a test that passes in a single process
  proves nothing about it.
- Production configuration with more than one instance and no shared atomic
  backend refuses to start, rather than running the check non-atomically.
- Production configuration with `duplicate_check` set to anything but
  `enforce` refuses to start.
- **With `direct_access` disabled, the page and the direct route both return
  404** — asserted, not assumed.
- `direct_access` absent from config behaves as disabled.
- With `duplicate_check: off`, the result and the page both say the check
  did not run; neither implies it passed.
- With the store unavailable, capture succeeds and the check degrades to a
  stated "could not check". A safety check that fails the request is a
  safety check that gets switched off.

## Out of scope

Detecting duplicates among orders that did not pass through this agent.
Anything that infers duplication from content. Blocking submission — the
agent does not submit.
