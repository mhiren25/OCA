<!-- draft proposal · import with /opsx:new 024-logging then /opsx:ff
     spec: api -->

# 024-logging

## Why

There is nothing to read when something goes wrong. The page shows a trace
of what the agent did, but that is one response to one uploader, held for 30
minutes and then gone — not a record you can search after a tester says
"it did something odd this morning".

## Structured logs to stdout, not to files

**No log files.** On Azure the container's stdout is what the platform
collects; a log file written inside the container is a file nobody can reach,
that survives no restart, and that fills the disk. The absence of log files
is the correct state — the gap is that stdout carries nothing useful.

So: stdlib `logging`, one JSON line per event, to stdout. Locally, redirect
it to a file if you want one. Nothing in the application knows or cares.

- `INFO` — lifecycle: request received, each pipeline stage completed with
  its duration, outcome, orders produced, review count, response sent.
- `DEBUG` — the detail that makes a failure diagnosable: which prompt
  template and version, model name and parameters, token counts, HTTP status
  and latency of each outbound call, the instrument queries issued and how
  many candidates each returned, cache hit or miss.
- `WARNING` — degraded but completed: a lookup timed out, the per-email cap
  was hit, a retry succeeded.
- `ERROR` — the request failed, with the exception type and where.

Level from config, injected at runtime. `INFO` by default, `DEBUG` switchable
without a redeploy — because the request you need to debug has usually
already happened.

## The rule that matters

**There is no log level at which client data is logged.** Not the email body,
not the prompt, not an extracted value, not an instrument name, not an
account reference. Not at `DEBUG`, not behind a flag, not "temporarily".

`DEBUG` is exactly where this leaks, because the instinct when something is
wrong is to log the input. The answer is that the input is already
reproducible by other means: the corpus for fixtures, a cassette for a
recorded call, and the page's own trace for a live run. A log line's job is
to say *which* request, *which* stage, *how long*, and *what outcome* — never
*what it said*.

Concretely: log the instrument query's **length and candidate count**, not
the query. Log the body's **byte count and line count**, not the body. If a
field is needed to diagnose something, the field *name* is loggable and its
value is not.

012 already requires this of the request log line. This change is where it
either holds across a whole logging implementation or quietly stops holding.

## Correlation

Every line carries the request id 012 already generates, plus the stage name.
One request's whole life is then one query in the log aggregator, and when
this becomes one agent among several, a draft traces back to the email it
came from.

The `progress` entries that drive the page's trace are **not** log lines and
are not written to the log. They go to the uploader in the response body;
they are not a record of the service. Keeping these two separate is what
stops the trace's useful detail from draining into a log aggregator that must
not have it.

## Acceptance

- One JSON line per event on stdout; nothing writes a log file.
- Every line carries the request id and the stage.
- A full successful capture at `DEBUG` contains no text from the email: a
  test runs a fixture and asserts no substring of the body, no extracted
  value and no instrument name appears anywhere in the captured output.
  **This is the test that matters.**
- Level is set by config with no code change.
- An exception produces one `ERROR` with a traceback and the request id.
- A timed-out lookup produces a `WARNING` and the request still succeeds.
- No `progress` entry appears in the log.

## Out of scope

Metrics and tracing. Log shipping and retention, which are the platform's
concern. Per-field accuracy recording — that is 014's correction report.
