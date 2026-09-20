<!-- draft proposal · import with /opsx:new 013-eval-runner then /opsx:ff
     spec: corpus -->

# 013-eval-runner

## Why

Everything built so far is unmeasured. The corpus exists, the extractor
exists, and nothing has ever compared one to the other. This is the change
that closes that loop and produces the first number.

## What changes

`evals/runner.py`

```
python -m evals.runner --dev
python -m evals.runner --fixture 0003-sunrise-sell-all
python -m evals.runner --dev --record          # write cassettes
python -m evals.runner --holdout               # sparingly
```

Per fixture: read `source.eml`, run ingest → sanitize → extract, compare the
resulting `CaptureEnvelope` against `expected.capture.json` using
`evals/scoring.py`. The runner orchestrates and reports; it does not decide
what is correct. Scoring logic stays in the referee.

## Output

`corpus/runs/<iso8601>-<prompt-hash>/report.json`, plus a readable summary on
stdout.

**The per-tag breakdown is the primary output, not the headline number.** On
18 fixtures one email is 5.5%, so most movement in the aggregate is noise and
chasing it is how a week disappears. What is actionable is "every
`bloomberg-ticker` fixture is fine and both `sell-all` fixtures produce an
Absolute quantity" — a category, with a cause.

**Every fabrication is listed individually**, never counted. Fixture, field,
what the label says, what the model produced. A fabrication count is a number
to feel bad about; the list is a thing to fix.

Line recall and line precision are computed and reported separately from
field scores (CO-5). Field scoring cannot see a dropped order — three of four
lines can score perfectly while a real client order vanishes.

Also per run: token counts and wall-clock, so cost per email is visible from
the start rather than discovered at scale.

## Gates

Exit non-zero on a hard gate (CO-6):

| gate | threshold |
|---|---|
| fabrications | 0 — hard |
| line recall | 100% — hard |
| exact match | at or above baseline |
| misses | within the agreed ceiling |

## The run manifest

Every report pins prompt version and hash, schema version, model ID, corpus
git commit, and the timestamp (CO-7). A run that cannot state its corpus
commit is not a measurement, because nothing later can reproduce it. Refuse
to run against a dirty `corpus/` working tree unless `--dirty` is passed, and
record that flag in the manifest when it is.

## Baselines

`corpus/baselines/baseline.json` holds the current accepted scores.
`--set-baseline` requires `--why "<reason>"` and writes that reason into the
file beside the numbers. A baseline that moved for a reason nobody recorded
is a baseline nobody can defend, and the whole point of the ratchet is that
lowering it is uncomfortable.

## Holdout discipline

`--holdout` appends a line — timestamp, prompt hash, scores — to
`corpus/runs/holdout-log.md`, and prints how many times the holdout has been
looked at so far.

Not a restriction, a mirror. Once you have iterated against a split it has
stopped being a measurement, and the way that happens is invisibly, one
justified peek at a time. Seeing "holdout checked 6 times" on the way past is
the cheapest possible guard.

With the current corpus every fixture is `dev`, so `--holdout` selects
nothing. Say so plainly and exit zero rather than reporting a vacuous 100%.

## Hard constraints

- The runner never writes to `corpus/fixtures/`. Not even to normalise
  formatting.
- A fixture that fails to load is a runner error, not a scored miss. A
  malformed fixture silently counting as a model failure is how a corpus rots
  without anyone noticing.
- No client holding or credential reaches a cassette or a report.

## Acceptance

- `--dev` on the current corpus produces a report with per-fixture,
  per-field and per-tag detail, and a manifest naming the corpus commit.
- A deliberately fabricated value in a scratch fixture produces a non-zero
  exit and names the fixture and field.
- A deliberately dropped line produces a line-recall failure distinct from
  any field miss.
- Two runs against the same cassettes produce identical reports.
- `--set-baseline` without `--why` is refused.

## Out of scope

Mapping to `OrderRequest`, enrichment, and any change to `scoring.py`.

## Before this lands

`scoring.py` should verify CM-4 — that `body[start:end] == raw_text` for
every mapped field — and report a span that does not contain its value as a
defect. Nothing enforces that today, which is why the live-text offset bug
found during 010 was invisible to the corpus. It is a small addition to a
protected file, so it is a human edit, not part of this change; but a runner
that reports provenance as correct without ever checking it is the same
failure one level up.
