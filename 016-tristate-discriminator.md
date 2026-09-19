<!-- draft proposal · import with /opsx:new 016-tristate-discriminator then /opsx:ff
     spec: capture-model -->

# 016-tristate-discriminator

## Why

`Mapped`, `Unmapped` and `Unresolved` from 001 carry no discriminator, so
their serialised form does not say which of the three a value is. That is
fine while they only live in memory. It stops being fine the moment anything
reads one back from JSON, which is now:

- **013**, the eval runner, deserialising `expected.capture.json`
- **`evals/scoring.py`**, which classifies each field by state
- **015**, whose acceptance is that every fixture round-trips

Structurally the three are near-indistinguishable — `Unmapped` and
`Unresolved` can both present as a dict of nulls — so without a tag the
reader infers state from which keys are absent. CM-1 exists precisely to keep
those three apart; a serialisation that cannot state which one it is has
discarded the distinction the model was built to carry.

**001 already solved this for the other union.** `Quantity` discriminates on
`kind`. The tri-state is the same shape of problem left untagged, so this is
an inconsistency inside 001 rather than a new requirement. It sits under
`capture-model`'s existing CM-1, not as a new capability.

## What changes

`src/trade_capture/domain/states.py`

- `Mapped` gains `state: Literal["Mapped"]`
- `Unmapped` gains `state: Literal["Unmapped"]`
- `Unresolved` gains `state: Literal["Unresolved"]`
- Export `TriState = Annotated[Mapped | Unmapped | Unresolved,
  Field(discriminator="state")]`

Field declarations elsewhere use `TriState` rather than the bare union, so
Pydantic validates by tag rather than by try-each-in-order — which is also
what makes a malformed state an error instead of a silent fallthrough to
whichever variant happens to accept it.

## The discriminator value: a decision, not a detail

`Quantity.kind` uses the class name (`"Absolute"`). The fixtures currently on
disk use `"MAPPED"` for state, because `scripts/build_fixture.py` wrote them
that way before this model existed.

**Use the class name for both.** `state: "Mapped"`, `kind: "Absolute"` — one
convention, and the tag is always the type it names. The alternative is to
keep `"MAPPED"` and document why two unions in the same module tag
themselves differently, which is a footnote someone will trip over later.

The churn is smaller than it looks: fixtures are generated, not hand-written,
so every `expected.capture.json` is rebuilt with one
`python scripts/build_fixture.py corpus/fixtures/`. No relabelling. Two
non-generated things need the same edit, both outside what an agent may
touch:

- `scripts/build_fixture.py` — emit the class-name form
- `evals/scoring.py` — read it

Those are a human's to change. `corpus/` and `scoring.py` are
CODEOWNERS-protected exactly so this kind of edit is deliberate.

## Acceptance

- `TriState` validates a tagged dict into the right variant, and a dict with
  an unknown or missing `state` raises rather than defaulting.
- `model_dump()` of each variant includes its `state`, and
  `model_validate(model_dump(x)) == x` for all three.
- `Unmapped` and `Unresolved` are distinguishable from their JSON alone, with
  no reference to which other keys are present.
- `evals/scoring.py` classifies a field from a `model_dump()` output
  unchanged — no structural inference anywhere in it.
- Every fixture, rebuilt, round-trips through `CaptureEnvelope`.

## Why this is its own change

It modifies a primitive belonging to archived, approved 001, and 015's
`design.md` commits that change to composition only. Amending a primitive is
worth its own line in the history rather than arriving inside a change whose
stated scope excludes it. 015 depends on this and resumes once it lands.

## Out of scope

Any other change to `states.py`. `Quantity` already has its discriminator and
is not touched, except that its `kind` values are confirmed to follow the
same class-name convention.
