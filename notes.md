# Why this fixture exists

The `sell all (91,647)` case: the client states **both** "all" and a figure.
This is the fixture that proves `Quantity` is a union — with a plain float
field there is nowhere to record that both facts were given.

If the position later turns out to be 91,500, that disagreement is the most
valuable thing the system can surface. So both survive the label, and neither
is reconciled.

## Judgement calls made here

**quantity → EntirePosition, not Absolute.** The client's instruction is
"sell all". 91,647 is their *assertion* of what they hold, not the order
quantity. Recording it as `Absolute(91647)` loses the word "all" and
silently turns an assertion into an instruction.

**order_type → UNRESOLVED.** The client never said MKT or gave a limit.
"at vwap" is a strategy, not an order type. Defaulting it to MARKET here
would be a fabrication — the mapper's job, not the label's.
*This is a project-wide decision: be consistent across all fifty.*

**account_ref → UNRESOLVED with raw_text.** "Peng Bao" is a bare line with no
label, and it is a person, not an account number. The extractor should
capture the raw text; resolving it is enrichment's job.

**instrument.resolved → null.** Labels record what the client SAID.
Enrichment has not run. Never put an ISIN in a label.

**unmapped → empty.** "Sent from Proton Mail for iOS" is boilerplate, which
sanitize segments. It is not an instruction the client gave, so it is not
`Unmapped`.

## What this fixture does NOT cover

Quoted threads, tables, multi-line, attachments, non-English. Deliberately —
each fixture should isolate a small number of phenomena so a failure names
its cause.
