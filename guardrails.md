# Guardrails

Every constraint that stands between a client's email and a draft order,
where it runs, what it catches, and **what happens when it fires**.

A guardrail with no defined failure behaviour is a metric. Three rows below
are marked `POLICY?` for exactly that reason.

Status: `✓` in place · `?` needs confirming · `✗` gap, see 027.

---

## Input

| | guardrail | runs at | catches | on failure |
|---|---|---|---|---|
| ✓ | Upload size cap | API boundary | oversized `.eml` | reject, 413, never truncate |
| ✓ | `.eml` parse | ingestion | malformed email | 400, readable message, never a partial capture |
| ✓ | Live-region sanitiser | ingestion | acting on quoted thread, signature, disclaimer | excluded from the prompt entirely |
| ✓ | Redaction (021) | before the prompt, when CID mode on | client identifying data reaching the model, page or correction store | **fails closed** — 422, no model call |
| ✓ | Untrusted-data framing | prompt construction | email text read as instructions | framing only — **nothing detects an attempt**, see ✗ below |
| ✓ | Output escaping | page render | markup in client email | escape fragments, then join with marks |

## Model output — structure

| | guardrail | runs at | catches | on failure |
|---|---|---|---|---|
| ✓ | Strict `json_schema` | provider call | output outside the schema | `POLICY?` — what the client does on a refusal or a schema failure is not written down |
| ? | Enum validation | capture boundary | out-of-vocabulary values | 025 added a test; whether `SUBSCRIBE` was passing *before* it was in the enum is still unconfirmed, and the answer says whether the boundary enforces at all |
| ✓ | **CM-4 span check** | runtime *and* scoring | a value quoting text that is not in the email | runs — the trace reports it — but `POLICY?`: block, warn, or log and ship is undefined |

CM-4 is the strongest guardrail here and the least common. Verifying that
the model quoted text that actually exists is what makes "zero fabrications"
a measurement rather than a hope.

## Semantics and business rules

| | guardrail | runs at | catches | on failure |
|---|---|---|---|---|
| ✓ | Never-guess (023) | enrichment | picking between ambiguous candidates | Unresolved + review item; blocking when no draft can be built |
| ✓ | No overwriting a captured value (005) | registry | a resolver replacing what the client said | resolver skipped, skip recorded |
| ✓ | One writer per field (005) | registration | two resolvers writing one path | `ValueError`, at startup |
| ✓ | Quantity precedence (011) | mapper | a resolver overriding the client's stated figure | client's figure wins, both survive in the envelope |
| ✓ | Validators (003) | post-map | business-rule violations | findings on the draft |

## Action and egress

| | guardrail | runs at | catches | on failure |
|---|---|---|---|---|
| ✓ | **The agent never submits** | architecture | accidental execution | returns payloads; a human files them |
| ✓ | Deny-list, incl. `lifecycleData.canSubmit` | mapper **and** API boundary | fields that must never leave | exception, not a warning |
| ✓ | No persistence (012) | API | client data at rest | nothing written; job state expires |
| ✓ | No client data in logs (024) | logging | leak to an aggregator | `payloads: none` outside dev; a config that forces redaction and enables payloads fails at startup |
| ✓ | Agent write restrictions | CODEOWNERS + `TC_AGENT` | the agent editing `corpus/`, `scoring.py`, acceptance tests, the deny-list | blocked at the tooling level |

## Gaps

| | gap | why it matters |
|---|---|---|
| ✗ | **Prompt injection untested** | the framing exists; nothing proves it holds, and no fixture exercises it. First question a security review asks. |
| ✗ | **No output volume caps** | an email yielding 200 orders has no defined behaviour |
| ✗ | **Model call resilience unspecified** | retry, backoff, timeout. Mean round trip 14.7 s against a median of 9.8 s — if part of that tail is silent retries, nobody currently knows |
| ✗ | **No circuit breaker for RDMSearch** | once 023 is live, a dead instrument service should degrade every capture to blocked drafts, not fail them |
| ✗ | No rate or cost limiting | not urgent behind the gateway, but unwritten |

---

*Each gap and each `POLICY?` is addressed in 027.*
