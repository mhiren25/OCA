<!-- draft proposal · import with /opsx:new 020-review-page then /opsx:ff
     spec: api -->

# 020-review-page

## Why

012 specified the page in six bullets, as an upload form for a stakeholder
demo. It has since become the thing testers and domain experts use
unsupervised to explore what the agent does — and the only artefact anyone
non-technical will ever judge this project by.

That is a different product from an upload form, and it currently has no
owner: part of it is in 012, part in 014, and the parts that matter most are
in neither.

This proposal owns the page.

## Who it is for and what they need

**A domain expert exploring.** Can I break it? What does it do with a
forwarded chain, a table, a vague account? Needs to try things quickly and
see what happened.

**A stakeholder being shown.** Does this invent things? Needs one screen that
makes the answer obvious without a technical explanation.

**A reviewer, eventually.** Is this draft right? Needs to check in seconds,
not re-read the email.

All three want the same thing: **the email and what the agent made of it,
side by side, with the connection between them visible.**

## What the page shows

### 1. The agent working, as it works

A trace that fills in as the job runs, one line per stage, each with its real
duration:

```
0.000  Parsed .eml — 1 part, text/plain, 4.2 KB
0.040  Live region: lines 3–11 of 47 — dropped quoted thread, signature, disclaimer
0.180  Calling model · temperature 0
4.760  Model responded in 4,580 ms
4.790  Captured 3 order intents
4.810  Provenance verified — 23 of 23 spans match the source
4.840  Accounts: 2 ipids supplied, 1 matched by rule, 1 unresolved
4.880  Mapped 3 OrderRequests — deny-list clean
4.910  Fields the client did not specify: 5 — left unset, never guessed
4.930  2 items need a human · nothing submitted
```

This does two jobs at once, which is why it is worth building. For a
stakeholder it is the architecture explained without a diagram — the
two-schema split, the sanitiser, the span check, code doing the account
matching rather than the model. For whoever is debugging a bad extraction it
is the first place to look.

Five seconds of staring at a spinner is also the worst moment in the current
page, and the only one everybody experiences.

**Every line is true.** It appears when its stage actually completed, carrying
the duration that stage actually took. No synthetic progress bar, no typing
animation, no fabricated intermediate steps. A domain expert who works out
that the bar is decorative will discount the numbers next to it, and those
numbers are the product.

### 2. What it ignored

The email rendered with the quoted thread, signature and disclaimer visibly
dimmed and labelled, and the live region highlighted. A toggle hides the
dropped parts entirely.

This is the single most convincing thing on the page and it is in no proposal
today. Everyone assumes the system reads the whole email and hopes for the
best. Seeing it discard a 38-line quoted chain and act on 9 lines changes the
conversation before a single extracted value is discussed.

### 3. The orders, linked to the words

Each extracted value hover-linked to the exact words that produced it, in
both directions: hover a value and the source highlights, hover the email and
the values it fed light up.

The provenance data already exists and is verified at zero span defects. This
is rendering it.

### 4. What it declined to fill, and why

Unresolved fields shown explicitly — **not omitted** — reading *the client
did not specify a price*, not an error state. Fields waiting on enrichment
say so distinctly: *not looked up yet*, which is a different thing from *the
client did not say*.

This is the project's central claim made visible. "It invented nothing across
840 fields" is a sentence people nod at; a field reading *the client gave a
cash amount, not a quantity* is a thing they believe. A blank that looks like
a bug undoes the argument; a blank that explains itself makes it.

### 5. The payload, collapsed

The raw `OrderRequest` per draft, available and closed by default.
Stakeholders asked for the Order response and should be able to see it
literally. Nobody non-technical should meet JSON unless they go looking.

## How the trace gets to the browser

**In the poll response, not over a stream.** The result endpoint grows a
`progress` array, appended to as each stage completes; the page polls it
about once a second and renders what is new.

No SSE and no WebSocket. Streaming responses through an enterprise API
gateway are a fight — buffering, idle timeouts, and a second protocol for the
gateway team to accept at the moment we are asking them to accept the first
one. The contract in 012 is `202` plus a poll, and this rides it unchanged.

It is also the better behaviour. A trace carried in the job's own state is
**replayable**: open the result of a job that finished an hour ago and the
trace is still there. A stream only exists for whoever was connected while it
ran, which is nobody, most of the time.

**The trace is not a log line.** 012 requires that server logs carry no
client data, and that stands. This array travels to the browser that uploaded
that email, in the same response as the extracted values themselves, so it
may name stages, counts, durations and what was dropped. Two rules keep the
distinction from eroding: `progress` entries are **never written to the
server log**, and entries are assembled from a fixed set of stage reasons
with counts — never by interpolating email text into a message string, which
is how client data ends up somewhere it was never meant to go.

## What the sanitiser has to return

Dimming the dropped regions needs more than the live region. `sanitize/`
currently answers *here is the part to act on*; the page needs *here is every
zone, its span, and why it was classified that way* — live, quoted, signature,
disclaimer, boilerplate.

That is a small change and a better shape regardless: the classification is
already computed and currently thrown away. It is also generic rather than
order-specific, so it belongs in the shared library (019) when that lands.

## Design

Treat it as a trading desk tool, not a product page: dense, precise,
restrained. Specifically —

- Two panes, email left and drafts right, stacking to one column at narrow
  widths. Email body in a mono face so the agent's view and the reader's view
  of the text are the same.
- One accent colour, used for the live region and the provenance highlight
  and nothing else. Semantic colour reserved for *needs a human*.
- Tabular figures everywhere quantities appear. A column of prices that does
  not line up looks wrong to this audience before they have read it.
- Respect the viewer's light/dark setting.
- **No framework and no build step.** One page, server-rendered or
  self-contained, shipping in the same image as the API. A toolchain here is a
  maintenance cost with no return.

## Hard constraints

**Everything from the email is escaped before it renders.** The page displays
attacker-controlled text by design, and an email body containing markup is
the obvious attack. Restated from 012 because it is the constraint most
likely to be lost when a page is rewritten for looks.

**Plain language throughout.** Not `execution.horizon` but *how to work it*.
Not `UNRESOLVED` but *the client did not specify a price*. The audience
includes people who will never see the schema.

**Nothing on this page submits anything.** Say so on the page. A page that
shows a filled-in order and has a button on it invites exactly one wrong
assumption.

## Relationship to 014

014 owns capturing and reporting corrections. The inline correction control
and the coverage checklist are page surfaces, so whichever change is built
second inherits them — the point is that they are built once, into this page,
not as a second interface alongside it.

If 014 is already underway, leave them there and treat this proposal as the
rest of the page.

## Acceptance

- The trace renders stage by stage as the job runs, and each entry's duration
  matches the stage's real elapsed time.
- Opening a completed job's result renders the full trace from stored state.
- No `progress` entry appears in a server log line, asserted by test.
- A forwarded email renders with the quoted part, signature and disclaimer
  dimmed and labelled, and the live region marked.
- Hovering an extracted value highlights its source words, and the reverse.
- Unresolved fields appear with a plain-language reason, distinguishing *the
  client did not say* from *not looked up yet*.
- An email whose body contains `<script>` renders harmlessly.
- The 14-row table fixture is legible without horizontal scrolling, at
  desktop and at phone width.
- Someone who has not seen the project can be handed the URL, upload an
  email, and explain back what the agent did — the only acceptance test that
  really matters here.

## Out of scope

Editing or submitting drafts. Authentication (012). The correction store
(014).
