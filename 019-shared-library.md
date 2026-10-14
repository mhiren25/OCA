<!-- draft proposal · import with /opsx:new 019-shared-library then /opsx:ff
     spec: project -->

# 019-shared-library

## Why

A payments-instruction agent is coming, and after it the rest of the trade
lifecycle. Most of what has been built here is not about orders at all:
parsing `.eml`, finding the live region under a quoted thread and a
signature, calling a model with record/replay, locating a quoted value back
in the body, and — the part that took longest — the entire labelling and
measurement apparatus.

Copying that into the next agent means two divergent copies within a quarter.
Publishing it to Nexus means the payments team consumes it, improves it, and
those improvements come back here.

**Not now because the code is ready to be a library — because the Nexus
publishing process is slow and worth starting while there is one consumer and
no pressure.**

## The test for what goes in

> Could a payments agent import this package and never encounter the word
> "order"?

Anything that fails that test stays here. If the capture envelope, the
mapper or the deny-list leak in, the payments team inherits a dependency on
this domain and the library is compromised from its first release.

| Goes in | Stays |
|---|---|
| `ingestion/` — `.eml` parsing, dedup, the capture reference | the extraction prompt |
| `sanitize/` — live region, quoted thread, signature, disclaimer | `CaptureEnvelope`, `OrderIntent` |
| `extraction/providers/` — provider ABC, the HTTP client, cassettes, `Exchange` | `mapping/` and the deny-list |
| the value locator and provenance derivation | enrichment resolvers |
| tri-state primitives, `Provenance`, the `Quantity` union | validators (003) |
| **the eval apparatus** — scoring, runner, corpus format, `scaffold_fixture`, `build_fixture` | |

The tri-state and `Quantity` are arguable — a payment instruction has an
amount, not an order quantity. Include the tri-state and `Provenance`, which
are genuinely generic; leave `Quantity` here until a second domain asks for
it. Easier to move something out later than to take it back.

## Two packages, not one

```
trade-capture-common          runtime: ingestion, sanitize, providers, locator, states
trade-capture-common[evals]   dev: scoring, runner, corpus tooling
```

The eval machinery is the most valuable thing to share and the thing you
least want inside a deployed image. An extra keeps both true, and keeps the
Docker layer from carrying pytest and the corpus tooling into production.

## The dependency rule, enforced

Generic modules must not import domain ones. Today that is probably true by
accident; once it is a package it has to be true on purpose, and discipline
is not a mechanism.

A test that fails the build if `ingestion`, `sanitize`, `providers` or the
locator import anything domain-shaped. Same principle as the deny-list and
the pre-commit hook: the rules that have held in this project are the ones
something checks.

## Version 0.x until there is a second consumer

The API is shaped by exactly one caller and has never been reviewed by anyone
who would use it differently. `0.x` says that honestly and keeps the freedom
to change a signature without a negotiation.

When the payments team adopts it, the interface gets its first real review
from someone with different needs. That is when 1.0 is earned — not before,
and not by this repo alone.

## What this is not

Not a framework, not a plugin system, not an abstraction over "any document
extraction agent". It is the code already written, moved, with its seams
made explicit. Anything added in the name of future flexibility is a guess
made from a single example.

## Acceptance

- `trade-capture-common` builds and publishes to the internal Nexus.
- This repo consumes it from Nexus and its own `src/` holds only the
  order-specific code.
- `pytest` is green and the eval numbers are unchanged — a refactor that
  moves the baseline is a refactor that changed behaviour.
- The import-direction test fails when a domain import is added to a generic
  module.
- Installing `trade-capture-common` without `[evals]` pulls in no test or
  corpus dependency.
- A short README stating what the package is for and that `0.x` means the API
  will move.

## Sequencing

**After 003.** This is a refactor with no user waiting on it, and 003 is what
stands between the testers and a URL.

Start the Nexus publishing paperwork now, in parallel — in this estate that
is the long pole, and it does not need the code to be finished.
