<!-- draft proposal · import with /opsx:new 005-enrichment-registry then /opsx:ff
     spec: enrichment -->

# 005-enrichment-registry

## Why

Three resolvers — client/account, instrument, position — and the third depends
on the first two, since a holding is keyed by account *and* instrument. Hand
sequencing those calls means rewiring the pipeline every time one is added.
Declared dependencies mean adding a resolver is registering it.

## What changes

`enrichment/registry.py`

- `Resolver` ABC with class vars `name`, `depends_on: tuple[str, ...]`,
  `reads: tuple[str, ...]`, `writes: tuple[str, ...]`, `mcp_tool: str`,
  `reasoning_required: bool`, and `async resolve(intent, context)`
- `Registry.register(resolver)` and `Registry.ordered() -> list[Resolver]`,
  topologically sorted
- `ValueError` on a cycle or an unregistered dependency
- `ValueError` at registration if two resolvers declare the same `writes`
  path
- `Registry.describe()` — the field-to-resolver-to-MCP table, printable

`reads` and `writes` are capture-model paths, e.g.

```python
class InstrumentResolver(Resolver):
    name        = "instrument"
    depends_on  = ()
    reads       = ("instrument.raw_text", "instrument.form",
                   "instrument.stated_currency", "instrument.stated_venue")
    writes      = ("instrument.resolved",)
    mcp_tool    = "instrument-master:search"      # pinned per EN-6
    reasoning_required = True                      # candidates → model picks

class PositionResolver(Resolver):
    name        = "position"
    depends_on  = ("account", "instrument")
    reads       = ("account_ref.resolved", "instrument.resolved")
    writes      = ("quantity.resolved_position",)
    mcp_tool    = "positions:holding"
    reasoning_required = False                     # keyed lookup, one answer
```

They are not documentation. Three things depend on them:

- **Nothing may write a field the client filled.** Before a resolver runs,
  its `writes` target must be `None` or `Unresolved`. A resolver that
  overwrites a captured value has replaced what the client said with what a
  system thinks, which is the failure this whole two-stage design exists to
  prevent. Assert it in the chain, not in each resolver.
- **Two resolvers writing one field** is caught at registration rather than
  discovered by whichever ran last.
- **The reviewer needs the provenance of a filled value**: "the positions
  service said this at 14:02" is a different claim from "the client said
  this", and the UI can only distinguish them if the writer is recorded.

`reasoning_required` documents a distinction worth preserving as resolvers
accumulate: **MCP as transport is not the same as the model deciding to call
it.** Instrument lookup benefits from model judgement — a fuzzy name yields
candidates, and choosing between an ORD and a CDI line of the same issuer is
semantic. A position read does not: it is a keyed lookup with one right
answer. Both go over MCP for uniform auth and observability, but both are
*called by orchestration code* on resolved keys (EN-7).

Where `reasoning_required` is true, the selection call chooses from the
returned candidates or answers "none of these". It must never emit an
identifier absent from the list — a fabricated ISIN produces a draft for a
real, wrong security and reads as correct to a reviewer.

## Out of scope

The resolvers themselves, MCP transport, and returning candidate sets. This is
the chain, not what hangs off it.

## Acceptance

- Registering position (depends on instrument and account), instrument and
  account in any order yields an ordering where position comes after both.
- A cycle raises ValueError naming a resolver in the cycle.
- Depending on an unregistered resolver raises ValueError naming both.
- Ordering is deterministic for a given registration set.
- Registering two resolvers that declare the same `writes` path raises
  ValueError naming both.
- A resolver whose `writes` target is already `Mapped` is skipped, and the
  skip is recorded. The captured value survives.
- `describe()` lists every field, the resolver that fills it, and its
  `mcp_tool`.
- A resolver that returns nothing does not raise. **An unresolvable value is a
  normal outcome that reaches the reviewer**, never an error condition.

## Risks

Growing this into a general workflow engine. It is a topological sort over a
handful of nodes. If it exceeds ~80 lines, it is doing too much.
