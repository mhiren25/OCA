<!-- draft proposal · import with /opsx:new 024-logging then /opsx:ff
     spec: api -->

# 024-logging

## Why

There is nothing to read when something goes wrong. The page's trace is one
response to one uploader, held for 30 minutes and then gone — not a record
you can search after a tester says "it did something odd this morning", and
not enough to debug a bad extraction or a failing SOAP call.

## Where logs go is configuration

The application emits structured records. Where they land is a config
choice, not a rule baked into the code:

- **a rotating file** — size-capped with a bounded number of generations, so
  it cannot fill a disk
- **stdout** — for a container whose platform collects it
- **both**

Default to a file locally and wherever nothing is scraping stdout, which
includes any UAT box that is a plain server rather than a collected
container. Default to stdout where a collector exists. One line of config,
no code change.

## Payload detail is an environment capability, not a log level

This is the distinction that matters, and getting it wrong in either
direction is expensive.

**`payloads: full`** — the complete LLM prompt and response, the full SOAP
request and response, extracted values. Everything needed to see exactly
what was asked and what came back.

**`payloads: none`** — shapes, counts, hashes, identifiers and durations.
No text from the email, no extracted values, no instrument names.

**The setting is not reachable from the log level.** `DEBUG` buys more
diagnostics; it never buys more client text. Someone raising the level on a
UAT box to chase a bug must not thereby start writing client email into a
log file.

Where each applies:

| environment | data | payloads |
|---|---|---|
| local dev | redacted corpus emails | `full` — there is nothing to protect |
| UAT | real client email | `none` |
| anything beyond | real client email | `none` |

**Unset means `none`.** Fail closed, as everywhere else in this project.

**Bind it to the redaction profile from 021.** The configuration that forces
redaction is the configuration that forces `payloads: none`. One switch, two
behaviours, so they cannot drift apart — an environment handling real client
email cannot be put into a state where it redacts the email and then logs
the prompt built from it.

## What you still get with payloads off

"We cannot see what request was made" should not be true even in UAT. With
`payloads: none`:

| | |
|---|---|
| prompt template | id and version |
| model | name, temperature, max tokens |
| **prompt hash** | of the fully rendered prompt |
| tokens | prompt and completion counts |
| response | finish reason, latency |
| SOAP | operation, which identifier *type* was used, result count, fault code |
| capture | orders found, fields mapped, fields unresolved, review count |

The hash is the useful one. Most "what did we send" questions are really
*did this run send the same thing as the one that worked*, or *did the
prompt change between these two deploys* — and a hash answers both without
reproducing a line of the email.

## Cassettes are the full-fidelity record

For a failing corpus fixture, the cassette already holds the exact request
and response, and it is better than a log line because it replays. When
something extracts wrongly, the cassette is the artefact to open, not the
log.

Which means local debugging has two complementary things: `payloads: full`
in the log for the live shape of a run, and the cassette for exact
reproduction. Neither needs the UAT log to carry client text.

## Levels

- `INFO` — lifecycle: request received, each stage completed with its
  duration, outcome, orders produced, review count, response sent.
- `DEBUG` — the diagnostics above, plus cache hits, retries, candidate
  counts at each rung of the resolver ladder.
- `WARNING` — degraded but completed: a lookup timed out, the per-email cap
  was hit, a retry succeeded.
- `ERROR` — the request failed, with exception type and location.

Level from config, switchable without a redeploy, because the request you
need to debug has usually already happened.

## Correlation

Every record carries the request id 012 generates, plus the stage name. One
request's whole life is one query, and when this becomes one agent among
several, a draft traces back to the email it came from.

The `progress` entries that drive the page's trace are **not** log records
and are not written to the log. They go to the uploader in the response
body. Keeping the two separate is what stops the trace's detail draining
into a log nobody intended to put it in.

## Acceptance

- Destination is config: file, stdout, or both, with no code change.
- The file handler rotates on size with a bounded generation count; a test
  proves it does not grow without limit.
- `payloads: full` logs the rendered prompt and the model response.
- `payloads: none` logs neither, at any level — **a test runs a fixture at
  `DEBUG` with `payloads: none` and asserts no substring of the email body,
  no extracted value and no instrument name appears in the output.**
- Raising the log level does not change payload behaviour.
- Payloads unset behaves as `none`.
- A configuration that forces redaction cannot also enable `payloads: full`;
  attempting it fails at startup rather than at the first request.
- With payloads off, a record still carries the prompt hash, template
  version, model, token counts and latency.
- Every record carries the request id and stage.
- No `progress` entry appears in the log.

## Out of scope

Metrics and tracing. Log shipping and retention, which are the platform's
concern. Per-field accuracy recording — that is 014's correction report.
