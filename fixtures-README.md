# Fixtures

One directory per fixture, two files in it:

    0001-sunrise-sell-all-with-figure/
      source.eml              redacted original, NOT pasted text
      label.yaml              THE ONLY FILE YOU EDIT
      expected.capture.json   generated — never hand-edited

Never commit unredacted email. See `docs/corpus-spec.md` section 3.

## The loop

```bash
python scripts/scaffold_fixture.py corpus/staging/ -o corpus/fixtures/
$EDITOR corpus/fixtures/0001-*/label.yaml
python scripts/build_fixture.py corpus/fixtures/0001-*
```

`scaffold_fixture.py` transcribes what it can and leaves the rest blank.
`build_fixture.py` turns your `label.yaml` into `expected.capture.json`,
deriving every character offset by finding your value in the body text.

## The four rules

**1. Count the orders before you look at a field.** One `orders:` entry per
order the client gave. Line recall is a hard 100% gate, so a fixture missing
an entry quietly lowers the bar instead of failing loudly — it is the one
labelling error the evals cannot catch for you.

**2. Copy values verbatim.** `build_fixture.py` locates each value in the body
to derive its offsets. A paraphrase is not found and the build fails. That is
deliberate: it makes a label that has drifted from its source impossible to
commit.

**3. Blank is an answer.** Leave a field empty when the client did not state
it — that compiles to `Unresolved`, which is a real, scored outcome. Use the
per-order `unmapped:` list when the client said something the schema cannot
hold. Never invent a plausible value to fill a gap; a fabricated label teaches
the extractor to fabricate, and fabrications are gated at zero.

**4. Tags come from `corpus/schema/tags.yaml`.** Nothing else validates.
Finding a phenomenon the list does not cover is a good outcome — add the tag
there in its own commit.

## You will never be asked to check an offset

Because you cannot, and neither can anyone else. You supply meaning; the
machine supplies coordinates. If it cannot place a value unambiguously it
stops and says which value in which order — it does not guess a row.

## Disagreements

The first ten fixtures are labelled by two people independently. Record every
disagreement in `label.yaml`, with how it was settled:

```yaml
disagreements:
  - field: orders[0].quantity
    a: "Absolute 91647"
    b: "EntirePosition, client_asserted 91647"
    resolved: b
    why: >
      The instruction is "all". 91,647 is the client's belief about the
      position, which may be stale. Labelling it Absolute makes the extractor
      pass by reading a number the client did not order.
```

An unresolved disagreement fails the build. That is the point of the field:
the disagreement is the corpus telling you the spec was ambiguous, and you
want to find that out on fixture 3 rather than after labelling twenty-seven
of them inconsistently. Every resolution becomes a rule in
`docs/corpus-spec.md` so the next labeller does not re-litigate it.

Two labellers on all fifty is expensive. The usual compromise: both do the
first ten, compare, write the rules down, then one does the rest.
