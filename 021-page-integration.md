<!-- draft proposal · import with /opsx:new 021-page-integration then /opsx:ff
     spec: api -->

# 021-page-integration

## Why

020 specifies what the page shows. This is the change that makes it show it
from a live request instead of hand-written markup, and it adds the one input
control the page needs that the API does not have: whether the uploaded email
contains client identifying data.

Design stays in 020; runtime behaviour and the request contract are here.
That is a seam, not the split this project just untangled — the page is
described in exactly one place, and this change describes what the server has
to hand it.

## Part 1 — wiring the page to the API

The flow is already defined in 012 and does not change: `POST /v1/capture`
returns `202` and a job id, `GET /v1/capture/{job_id}` returns the result.
The page does that, polls about once a second, and renders.

Three things the server has to supply that it does not today.

**`progress` on the job state.** The trace in 020 needs one entry per stage,
appended as that stage completes, readable from the pending response. The
stages already exist as code boundaries — parse, sanitise, prompt, model,
capture, span check, account match, map, deny-list — so this is instrumenting
them, not restructuring anything.

**Zones from the sanitiser.** 020 covers this: `sanitize/` must return every
zone with its span and classification, not only the live region. The page
cannot dim what it was not told about.

**The body, pre-segmented.** The page highlights `body[start:end]`, so the
body it renders must be the same body the spans were computed against — 010
was this bug once already. Rather than return the body and the offsets and
trust the page to cut it correctly, **the server returns the body already cut
into fragments**, each carrying the span ids it belongs to.

That is one extra field and it removes an entire class of bug. Offsets are
computed in Python, where a string index is a code point; the page would
re-apply them in JavaScript, where a string index is a UTF-16 code unit. One
non-BMP character anywhere in the email — an emoji in a signature is enough —
and every highlight after it lands on the wrong words, on exactly the kind of
email nobody tests with. Cutting where the offsets were computed means the
page never does offset arithmetic at all.

The cost is the body appearing twice in the response if the raw body is also
returned. It should not be: the fragments are the body.

No new endpoints, no new contract, nothing for the gateway team to re-import.

## Part 2 — the CID toggle

A checkbox on the upload form declaring what is in the file:

> **This email contains client identifying data** — on by default.

On, the server redacts before anything else touches the email. Off, the
uploader is asserting the file is already clean — a synthetic test email, or
one already through the corpus redaction path — and no redaction runs.

### It defaults to redact, and absence means redact

The field missing, empty, or unparseable means the email contains CID. A
control that protects client data by default-off is a control that is off.

### The mode is declared, never inferred

No heuristic decides this. "It looks like it has already been redacted" is a
guess, and a wrong guess in the permissive direction puts real client names
into a prompt, a page, a trace and any correction stored against it. The
uploader states it; the server believes them and records that they did.

### Config can take the choice away

In the environment where real client email arrives, the toggle should not
exist: redaction is forced, the field is ignored, and the page does not offer
it. Same shape as the dev endpoint in 014 and the direct URL in 012 — the
permissive setting is a development convenience, and the environment that
must not have it does not have it.

Which means two config states, not a global flag: *choice offered* for dev,
*always redact* for UAT and anything facing real email.

### The assertion is recorded; the content is not

A log line carrying the request id, the asserting principal from the JWT, and
the mode. No email text, consistent with 012.

Someone will tick "no CID" on a real client email eventually. When that
happens you need to be able to establish which requests ran unredacted and
who asserted it — and the answer cannot be reconstructed from a store that,
per 012, keeps nothing.

### Redaction in the request path is not the corpus tool's job

`redact.py` exists to build the corpus, and it writes a mapping file —
`~/.tca-redaction-map.json`, the re-identification key. **Nothing in the
request path writes that file.**

Within one email, pseudonyms must be consistent: the same client name has to
redact to the same token every time it appears, or provenance spans stop
matching and account matching breaks. That needs a map. It does not need a
*persisted* map.

So the request path builds a map in memory, uses it for that one email,
and discards it when the job expires. Within-document consistency, no
cross-document consistency, no key written anywhere. The corpus tool keeps
its persistent map because re-identification is the point there; here it is a
liability with no use.

A correction stored under 014 snapshots redacted text and nothing else, so
the retention question that proposal raises gets materially smaller.

### One coordinate frame

When redaction runs, **the redacted body is the body** — the text sent to the
model, the text the spans index, the text the page renders, the text a
correction snapshots. The original is used to produce the redacted version
and then dropped.

The failure mode to design out is redacting for the prompt and displaying the
original. That reintroduces 010's bug, and worse, it puts the unredacted email
on a page whose whole purpose was that the data on it is safe to look at.

### It fails closed

If redaction errors — a parse failure, an encoding it cannot handle, a
pathological input — the request fails with a 422 and a readable message. It
does **not** fall through to the model with the original text. The one
outcome this must never have is "redaction didn't work, so we sent it
unredacted".

### Measure what it costs

`redact.py` has only ever run offline in batch, where a second per email is
free. It is now inside the gateway's budget alongside a 5-second model call.
Measure it on the largest fixture before building the rest; if it is slow
enough to matter, that is worth knowing while the design is still open rather
than after the page is wired.

### The page has to say which mode ran

A banner stating the mode, and when redaction ran, how many identifiers were
replaced:

> Redacted before processing — 7 identifiers replaced.

Not decoration. A tester shown a page of pseudonyms with no explanation files
a correction saying the agent got the client name wrong, and your per-field
correction rate from 014 acquires a column of noise generated entirely by the
UI. Tell them, and that whole class of false correction disappears.

### What redaction does not touch

`account_ipids` arrive in the request as internal identifiers, are consumed
by code, and never enter a prompt. They are not redacted and they are not
rendered on the page beyond the matched result.

## Part 3 — the page's own code

The mock-up is a static file with its data written into the markup. This is
what turns it into the served page.

### Where it lives, and what it is

`src/trade_capture/api/static/review.html`, committed, served by `GET /`.
The mock-up is the starting point rather than a reference to re-implement.

**The shell is static; the data arrives as JSON and the page renders it.**
Not server-side templating — the flow is asynchronous, so a templated page
would need either a re-render per poll or a second partial-rendering
endpoint, and that endpoint would be a second representation of the result
that can drift from the documented one.

Rendering client-side from the response the API already returns means the
page consumes exactly the published contract. It is then also a working
reference implementation for whoever integrates next, which is worth more
than it costs.

No framework, no build step, no bundler. One HTML file with its CSS and JS
inline, or a template plus one static script. A toolchain here is a
maintenance cost with no return.

### Escaping, where the marks go in

This is the part to get right, because done naively it is an XSS hole in the
one page that renders attacker-controlled text by design.

**Never escape the body and then insert `<mark>` tags at the provenance
offsets.** Escaping changes the text's length — one `&` becomes five
characters — so every offset after the first escaped character is wrong.

**Never insert the marks and escape afterwards.** That escapes your own tags
and the page shows them as text.

The only correct order: cut the body at the span boundaries, escape each
fragment, then join the fragments with the marks between them. Part 1 moves
the cutting to the server, so the page's job is reduced to escape-and-join —
and the test that matters feeds a body containing `<`, `&`, a quote and a
non-ASCII character, and asserts both that the marks land on the right words
and that nothing renders as markup.

Build it as one function. Every place that puts email-derived text on the
page goes through it, including the zone labels and anything quoted into a
review item.

### The states the mock-up does not have

The mock-up has one state: finished, successfully. The real page needs:

| | |
|---|---|
| idle | no file chosen yet |
| running | the trace filling, no result yet |
| done | drafts rendered |
| **no orders found** | not an error — 012 requires this be said plainly |
| 400 | the `.eml` would not parse |
| 413 | too large; say the limit |
| 422 | redaction failed (Part 2) — no partial result shown |
| 404 | **"expired or unknown"**, in those words, per 012 — a restart loses outstanding ids and a routine deploy must not read as a bug |
| still pending | past the gateway's window; keep polling and say so |
| poll failed | the network dropped, not the job |

Nine of those eleven are the ones a tester will actually hit on day one, and
a page that shows a blank panel for any of them generates a bug report about
the agent rather than about the upload.

### Polling has a limit

Backoff, and a bounded number of attempts, then stop and say what happened.
A page that polls a dead job id every second until the tab is closed is a
quiet load generator pointed at your own service, and it will be left open
overnight.

### The job id goes in the URL

`#job=<id>` so a reload resumes rather than losing the result, and so a
tester can send a colleague the link to what they just saw. Worth saying on
the page that the link dies with the job's 30-minute TTL — otherwise someone
pastes one into a ticket and it is empty by the time it is read.

### Provenance cannot be hover-only

Hover excludes keyboard and touch entirely. Focus and tap both pin a
highlight, and the trace is a polite live region so it is announced as it
fills rather than read as a wall at the end. Respect
`prefers-reduced-motion`.

## Acceptance

- The page takes a file, posts it, polls, and renders the trace, zones,
  drafts and provenance from the live response.
- A body containing `<`, `&`, `"` and a non-ASCII character renders with no
  markup interpreted and the highlights on the correct words — one test,
  asserting both.
- An email containing a non-BMP character highlights correctly.
- Each of the eleven states above renders something a tester can read.
- An unknown job id reads "expired or unknown", not "invalid".
- Polling backs off and stops; the page says why.
- A reload with `#job=<id>` resumes the result.
- Provenance works by keyboard and by tap, not only by hover.
- The rendered body is byte-identical to the body the provenance spans index,
  asserted by test.
- A request with no CID field redacts.
- A request asserting no CID does not redact, and the assertion appears in
  the log line with the principal.
- In always-redact configuration, a request asserting no CID is redacted
  anyway and the page does not show the toggle.
- The same client name appearing three times in one email redacts to the same
  token all three times.
- No mapping file is written by any request, asserted by test.
- Redaction raising an exception produces a 422 and no model call —
  asserted by test, because this is the one that matters.
- The page states which mode ran, and the replacement count when redaction
  ran.
- Redaction latency on the largest corpus fixture is measured and recorded in
  the change.

## Out of scope

Page design (020). The correction store (014). Cross-document pseudonym
stability — deliberately not provided here. Anything that re-identifies a
redacted response.
