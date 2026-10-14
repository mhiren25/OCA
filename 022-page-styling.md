<!-- draft proposal · import with /opsx:new 022-page-styling then /opsx:ff
     spec: api
     after: 021 synced and archived -->

# 022-page-styling

## Why

021 built the page and it works. It looks plain, because 020 and 021
described the design in prose and prose cannot specify a visual design — an
agent given adjectives produces something correct and unremarkable, which is
exactly what happened.

The fix is not a better description. It is a committed stylesheet and a
structure contract, so the design is an asset the page links rather than a
reading someone re-derives each time.

Presentation only. No behaviour changes.

## What changes

**Two files land, both committed:**

- `src/trade_capture/api/static/review.css` — tokens for both themes, type,
  layout, and every component rule: the trace strip, email zones, provenance
  highlighting, draft cards, notices, and the page states.
- `docs/design/markup-contract.md` — the structure that stylesheet expects.
  Class names, what wraps what, the `data-prov` convention on both sides of a
  provenance link, which element carries `is-last`.

**`review.html` is rewritten to match the contract** and to link the
stylesheet. Whatever ad-hoc CSS the page carries today is removed.

**The rule that keeps it true:** the page has no inline `<style>` block and
no `style=` attributes. A new element gets a rule in `review.css` and a line
in the contract. This project's conventions have held where something checks
them — the deny-list, the pre-commit hook, the span check — so this one is a
test over the served page, not a note.

## No external font host

The design uses IBM Plex where it is installed on the viewer's machine and
falls back to the system stack. **No `fonts.googleapis.com` link, no
`@import`, no CDN.**

The UAT server sits behind the firewall. A page whose appearance depends on
whether a font request escaped the network is a page that cannot be judged,
and the first report would be "it looks different on the server" with nobody
able to reproduce it.

## What this is not

No endpoint changes, no contract changes, nothing the gateway re-imports. No
new page states — the eleven from 021 keep their behaviour and gain styling.
No change to what the page says, only to how it reads.

Two classes in the stylesheet are deliberately unused for now:
`.tag-invalid` and `.chip--invalid`, for 003's validator findings. They exist
so that when 003 lands it renders findings through the existing design
instead of inventing a second visual language for them. **Do not render them
in this change** — there are no findings to render yet.

## Acceptance

- `review.html` contains no `<style>` block and no `style=` attribute,
  asserted by a test against the served page.
- Every class the page uses appears in `review.css`; every class in the
  contract that the page should use, it uses.
- The page renders with no outbound network request — asserted, since this is
  the condition on the UAT server.
- Both themes render legibly: nothing takes a colour that works in only one.
- The visual test set from 021 renders legibly at desktop and phone width:
  the widest (14-row table), the longest, the emptiest, the non-English one.
  If 021 did not exercise these, it is exercised here.
- The email body's own newlines are the line breaks — no `<br>` inserted.
- Provenance still lights both directions, and still by keyboard and tap.
- No eval number moves. Nothing in this change touches extraction, mapping or
  the API, so a baseline that shifts means something was changed that
  shouldn't have been.
