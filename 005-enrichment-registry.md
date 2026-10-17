<!-- draft proposal · import with /opsx:new 005-enrichment-registry then /opsx:ff
     spec: enrichment
     amended 2026-10-17 — see "What changed" below -->

# 005-enrichment-registry

## What changed from the original draft

The original predates 016, 018 and 023, and four things in it were wrong by
the time they were needed:

1. **`mcp_tool` → `service`.** The ABC named a transport. 023 settled that
   the instrument service is reached by a plain SOAP client, not MCP, so the
   field names the service and config picks the client.
2. **The instrument `reads` list was stale.** It named
   `instrument.raw_text` and `instrument.form`, which 018 replaced with
   three independent tri-state identifier fields.
3. **`reasoning_required` is gone.** It encoded "candidates → model picks",
   and no resolver does that any more.
4. **Instrument `depends_on` is no longer empty.** It needs the account's
   currency and market.

## Why

Three resolvers — account, instrument, position — and the third depends on
the first two, since a holding is keyed by account *and* instrument. Hand
sequencing those calls means rewiring the pipeline every time one is added.
Declared dependencies mean adding a resolver is registering it.

## What changes

`enrichment/registry.py`

- `Resolver` ABC with class vars `name`, `depends_on: tuple[str, ...]`,
  `reads: tuple[str, ...]`, `writes: tuple[str, ...]`, `service: str`, and
  `async resolve(intent, context)`
- `Registry.register(resolver)` and `Registry.ordered() -> list[Resolver]`,
  topologically sorted
- `ValueError` on a cycle or an unregistered dependency
- `ValueError` at registration if two resolvers declare the same `writes`
  path
- `Registry.describe()` — the field-to-resolver-to-service table, printable

`reads` and `writes` are capture-model paths:

```python
class InstrumentResolver(Resolver):
    name        = "instrument"
    depends_on  = ()                    # becomes ("account",) when that exists
    reads       = ("instrument.name", "instrument.ticker", "instrument.isin",
                   "instrument.stated_currency", "instrument.stated_venue",
                   "side")
    writes      = ("instrument.resolved",)
    service     = "rdm-search"

class PositionResolver(Resolver):
    name        = "position"
    depends_on  = ("account", "instrument")
    reads       = ("account_ref.resolved", "instrument.resolved")
    writes      = ("quantity.resolved_position",)
    service     = "positions"
```

### No account resolver in phase one, and no placeholder for one

The account resolver is deferred — accounts are often absent from the email
anyway, and the ipids arrive in the request. Two consequences.

**Instrument declares `depends_on = ()`.** Declaring `("account",)` against
a resolver that is not registered makes `Registry.ordered()` raise, by this
proposal's own rule, and that rule is worth keeping strict. The dependency
goes in when the resolver does.

**Do not register a placeholder that does nothing.** It would appear in
`describe()`, read as implemented, and let someone later assume accounts are
handled. An absent resolver is honest; a no-op one is a lie with a test
suite. A line in this proposal saying it is planned is the whole placeholder
needed.

When it is built, note that it is smaller than it looks: 012 already
specifies matching the client's words to a supplied ipid in code, so the new
part is only the account-master call that returns the account's currency and
market.

**Check `stated_currency` and `stated_venue` still exist.** They are listed
because 023's first filter reads them, but 018 restructured the instrument
fields and may have dropped them. If it did, that is a capture change before
either this or 023 — a currency the client wrote and the schema cannot hold
never reaches a resolver.

### `service` names a service, not a transport

How a resolver reaches its service — SOAP client, REST client, MCP, a local
table — is a deployment choice resolved from config. The ABC should not
encode it, because changing transport should not mean editing a resolver,
and because this project now has one of each: `rdm-search` is SOAP (023),
and nothing is MCP.

### Why `reads` and `writes` are not documentation

Three things depend on them:

- **Nothing may write a field the client filled.** Before a resolver runs,
  its `writes` target must be `None` or `Unresolved`. A resolver that
  overwrites a captured value has replaced what the client said with what a
  system thinks, which is the failure this whole two-stage design exists to
  prevent. Assert it in the chain, not in each resolver.
- **Two resolvers writing one field** is caught at registration rather than
  discovered by whichever ran last.
- **The reviewer needs the provenance of a filled value.** "The positions
  service said this at 14:02" is a different claim from "the client said
  this", and the page can only distinguish them if the writer is recorded.

## The ambiguity policy, which replaces `reasoning_required`

The original flag marked instrument lookup as needing model judgement to
choose between candidates. 023 removed that: **no resolver asks a model to
choose an identifier**, because the information that decides between an ORD
and a CDI line is the client's mandate, not anything in the email, and a
confident wrong ISIN names a real security and reads as correct to a
reviewer.

So every resolver follows the same policy, and it needs no flag:

> **Narrow deterministically, then surface.** Apply filters the data or the
> client's own words justify. Where several candidates remain, leave the
> field Unresolved and emit a review item naming them. Never pick.

A resolver that finds exactly one answer writes it. A resolver that finds
none or several writes nothing and says why.

## Resolvers may decline to run

Ordering is not the same as running. The position resolver is called **only
for sell-all** — every other case takes the client's stated quantity, by the
precedence decided in 011. So a resolver may inspect the intent and return
without calling its service.

Declining is not an error and not a review item. It is recorded in the trace
so a reader of the log can tell "did not need to run" from "ran and found
nothing", which otherwise look identical from the outside.

## Out of scope

The resolvers themselves and their clients — 023 is the first. Returning
candidate sets. This is the chain, not what hangs off it.

## Acceptance

- Registering position (depends on instrument and account), instrument and
  account in any order yields an ordering where account precedes instrument
  and both precede position.
- A cycle raises ValueError naming a resolver in the cycle.
- Depending on an unregistered resolver raises ValueError naming both.
- Ordering is deterministic for a given registration set.
- Registering two resolvers that declare the same `writes` path raises
  ValueError naming both.
- A resolver whose `writes` target is already `Mapped` is skipped, and the
  skip is recorded. The captured value survives.
- A resolver that declines to run is distinguishable in the trace from one
  that ran and resolved nothing.
- `describe()` lists every field, the resolver that fills it, and its
  `service`.
- A resolver that returns nothing does not raise. **An unresolvable value is
  a normal outcome that reaches the reviewer**, never an error condition.

## Risks

Growing this into a general workflow engine. It is a topological sort over a
handful of nodes. If it exceeds ~80 lines, it is doing too much.
