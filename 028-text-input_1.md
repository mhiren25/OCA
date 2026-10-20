<!-- draft proposal · import with /opsx:new 028-text-input then /opsx:ff
     spec: api -->

# 028-text-input

## Why

Stakeholders asked for a chat window in the Draft Order screen. Stripped of
the parts that were declined — conversational editing, question answering —
what remains is simply: **people have the instruction as text, not as a
file.** Pasted from a thread, copied off a phone, forwarded without the
original.

Requiring an `.eml` makes them manufacture a file to get at something the
agent could read directly.

## What changes

### The API takes text or a file

`POST /v1/capture` gains a `text` field alongside `email`. **Exactly one is
required**, and supplying both is a 400 rather than a silent preference —
the caller does not know which the server would pick, so neither should the
server guess.

Everything else is unchanged: same async contract, same job, same result
shape, same `account_ipids` and `idempotency_key`.

**The OpenAPI contract changes**, which means regenerating it and the
gateway team re-importing. Administratively the slowest part of an otherwise
small change, so start that conversation when the change opens rather than
when it closes.

### The sanitiser runs on text too

This is the decision that matters.

The temptation is to treat pasted text as entirely live region — the user
chose it, there are no headers to strip. **Don't.** People paste forwarded
emails constantly, quoted chain and signature included. Skip the sanitiser
and the agent captures orders out of last week's quoted history, and nothing
on the page shows that it happened.

Run the same sanitiser. It finds structure when there is structure and finds
none when there is not, and a clean paragraph simply yields one live zone.

Which makes the *what it ignored* panel **more** valuable for text than for
a file, not less: with an upload the user knows what they handed over; with
a paste, especially one off a phone or out of a long thread, they often do
not.

### What text does not carry

**No `From`, `Sent` or `Subject`.** The page's meta block needs an absent
state rather than empty rows. Confirm nothing downstream reads the sender —
account matching should not, since ipids arrive in the request, but it is
worth checking rather than assuming.

**No `Message-ID`.** Today this changes nothing, and an earlier draft of
this section was wrong to imply otherwise.

The current state, verified in code: `ingestion/dedup.py` is an
unimplemented stub left by **004-capture-reference, which was never built**.
`capture_id` is a fresh ULID on every capture in `run_capture()`, never
derived from the email. The only duplicate mechanism that exists is the
caller-supplied `idempotency_key`, which is input-agnostic and works
identically for a file or for text.

So **this change creates no asymmetry between the two inputs.** Both get a
ULID `capture_id`; neither is checked against anything.

The asymmetry arrives with 029, which derives identity from `Message-ID`.
From that point an attached `.eml` can be duplicate-checked and a paste
cannot — a difference worth putting in front of whoever chooses between
them, but 029's to state, not this change's.

What 028 does owe 029: the text path must carry *no* `Message-ID` rather
than an empty or synthesised one, so the later check can tell "absent" from
"present and blank" without guessing.

### The page takes both

One page, one submit. A file input and a text area, with submit enabled when
either has content.

**It should look like a paste box, not a message thread.** The stakeholders
said "chat window" because that is the shape they pictured for pasting text,
not because they want a dialogue — and conversation was deliberately
declined. A UI that looks like chat will be expected to reply, and then
asked why it doesn't.

### Guardrails apply identically

The size cap, the untrusted-data framing in the prompt, and the escaping
before render all apply to pasted text exactly as to an uploaded file. The
guardrail inventory should say *either input* rather than *the uploaded
file*, so the next person reading it does not assume text took a shortcut.

Pasted text is no more trustworthy than an email; it just arrived by hand.

## Corpus

Every fixture today is an `.eml`. The shared pipeline is covered by them,
but the text adapter is not. Two fixtures close it cheaply:

- a clean pasted paragraph, no email structure at all
- a pasted forward, headers and quoted chain included, where the live region
  is a fraction of what was pasted

A `pasted-text` tag so they are visible on 014's coverage checklist.

## Acceptance

- A capture from `text` produces the same result shape as one from `email`.
- Supplying both, or neither, is a 400.
- A pasted forward has its quoted chain and signature excluded, and the page
  shows them as dropped zones.
- A clean paragraph yields one live zone and no dropped zones.
- The meta block renders an absent state rather than empty rows.
- A text capture carries no `Message-ID` at all — not an empty string, not a
  synthesised one — so 029 can later distinguish absent from blank.
- The size cap rejects oversized text with the same message as an oversized
  file.
- Text containing `<script>` renders harmlessly.
- `api/openapi.yaml` regenerates, stays self-contained, and the gateway team
  has re-imported it.
- The two new fixtures pass the gate and appear on the coverage checklist.

## Out of scope

Conversational editing — declined; the form is faster and the agent has no
provenance for a value the trader spoke. Question answering over a capture —
declined for now; it would need its own eval corpus before it could be
trusted, and an unmeasured answer beside measured fields is worse than no
answer.
