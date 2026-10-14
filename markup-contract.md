# Review page — markup contract

`static/review.css` is the source of truth for how the review page looks.
This file is the structure that stylesheet expects. An agent asked to build
or change the page renders markup matching this contract and does not invent
class names or write new CSS; a genuinely new element gets a rule added to
`review.css` and a line added here.

Design decisions live in the stylesheet, not in prose. Do not re-derive the
appearance from a proposal.

## Document

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Trade Capture — review</title>
  <link rel="stylesheet" href="/static/review.css">
</head>
<body>
  <!-- header, trace, layout -->
  <script src="/static/review.js"></script>
</body>
</html>
```

No external font or script host. The UAT server is behind the firewall and
the page must render identically with no outbound network.

## Header

```html
<header class="page-header">
  <div class="page-header__in gutter">
    <div class="brand">Trade Capture <span class="brand__sub">/ review</span></div>
    <div class="filename">rebalance-14oct.eml</div>
    <div class="spacer"></div>
    <button class="btn" type="button" id="run-again">Run again</button>
  </div>
</header>
```

## Agent trace

The container takes exactly one of `is-running`, `is-done`, `is-error`.
Rows are appended as `progress` entries arrive; nothing is pre-rendered and
no entry is synthesised.

```html
<section class="trace is-running" id="trace">
  <div class="trace__in gutter">
    <div class="trace__head">
      <span class="trace__pulse"></span>
      <span class="trace__title">Agent working</span>
      <span class="trace__elapsed">4.93 s</span>
    </div>
    <div class="trace__log" role="log" aria-live="polite" aria-label="Agent trace">
      <div class="trace__row">
        <span class="trace__t">4.810</span>
        <span class="trace__m">
          Provenance verified — <span class="is-ok">23 of 23 spans match</span>
        </span>
      </div>
    </div>
  </div>
</section>
```

Emphasis inside `trace__m`: `<strong>` for a figure, `.is-ok` / `.is-warn` /
`.is-bad` for outcome. Nothing else.

## Notices

Above the layout. Used for the redaction mode banner (021 Part 2) and for
anything that applies to the whole response.

```html
<div class="notice notice--ok">
  Redacted before processing — <span class="notice__count">7</span> identifiers replaced.
</div>
```

Variants: `notice--info`, `notice--ok`, `notice--warn`, `notice--error`.

## Layout

Two panes. Collapses to one column under 1000px — do not add breakpoints.

```html
<main class="layout gutter">
  <section>
    <div class="pane__label">
      <span>Source email</span>
      <span class="spacer"></span>
      <label class="toggle"><input type="checkbox" id="hide-dropped"> Hide what was ignored</label>
    </div>
    <!-- .email -->
    <p class="pane__note">47 lines in, 9 acted on.</p>
  </section>
  <section>
    <div class="pane__label">
      <span>Captured orders — 3 drafts</span>
      <span class="spacer"></span>
      <span>2 items need a human</span>
    </div>
    <!-- .drafts -->
  </section>
</main>
```

## Email pane

`.email__body` has `white-space: pre-wrap`, so the body's own newlines are
the line breaks — never `<br>`.

Each zone is one `<span class="zone zone--…">` wrapping a `.zone__tag` label
and then the zone's text. Zones come from the sanitiser; the page does not
classify.

```html
<div class="email">
  <dl class="email__meta">
    <dt>From</dt><dd>ops@client.example</dd>
    <dt>Sent</dt><dd>Thu 14 Oct 2026, 10:58 +0800</dd>
    <dt>Subject</dt><dd>RE: Portfolio rebalance</dd>
  </dl>
  <div class="email__body" id="email-body"><span class="zone zone--live"><span class="zone__tag">Live region · lines 3–11 · the agent acts on this</span>Buy <mark class="prov" data-prov="q1" tabindex="0">USD3mil</mark> of …</span><span class="zone zone--dropped"><span class="zone__tag">Quoted thread · dropped</span>&gt; From: …</span></div>
</div>
```

Zone variants: `zone--live`, `zone--dropped`. The classification itself goes
in `.zone__tag` text, so a new zone kind needs no new class.

**Escaping.** Fragments arrive pre-cut from the server (021 Part 1). Escape
each fragment, then join with the `<mark>` elements between them. Never
escape the whole body and insert marks at offsets, and never insert marks
then escape.

## Provenance

`data-prov="<span id>"` on both sides — the `<mark>` in the email and the
`.value` in the draft. Hovering, focusing or tapping either adds `is-lit` to
every element sharing that id, and `is-lit` to the `<dd>` and its `<dt>`.

Marks carry `tabindex="0"` so the link works by keyboard.

## Draft cards

```html
<div class="drafts">
  <article class="card">
    <div class="card__head">
      <span class="card__idx">1</span>
      <span class="side side--buy">BUY</span>
      <span class="card__name">Nestlé 1.375% 2029</span>
      <span class="chip chip--review">1 to check</span>
    </div>
    <dl class="fields">
      <dt>Cash amount</dt>
      <dd><span class="value" data-prov="q1" tabindex="0">USD 3,000,000</span></dd>

      <dt>Quantity</dt>
      <dd><span class="unresolved">the client gave a cash amount, not a quantity</span></dd>

      <dt>ISIN</dt>
      <dd><span class="unresolved">not looked up yet <span class="tag-pending">instrument service pending</span></span></dd>

      <dt class="is-last">Good until</dt>
      <dd class="is-last">end of today <span class="qualifier">(default — the client did not say)</span></dd>
    </dl>
    <div class="card__foot">
      <details>
        <summary>Order payload</summary>
        <pre class="payload">{ … }</pre>
      </details>
    </div>
  </article>
</div>
```

Rules the stylesheet assumes:

- Every field is a `<dt>`/`<dd>` pair. The last pair carries `is-last` on both.
- A value the client stated → `.value`, with `data-prov`.
- A value the client did not state → `.unresolved`, whose text is the reason
  in plain language. The `::before` em-dash is supplied by CSS; do not write one.
- A derived or defaulted value is plain text plus `.qualifier` for the why.
- `.tag-pending` for awaiting enrichment, `.tag-invalid` for a validator finding.
- Chips: `chip--clean`, `chip--review`, `chip--invalid`.

## Page states

The eleven states in 021 Part 3 all render through `.state`, except idle,
which renders `.upload`.

```html
<div class="state">
  <p class="state__title">That job has expired or is unknown</p>
  <p class="state__body">Results are kept for 30 minutes. Upload the email again to re-run it.</p>
  <p class="state__detail">job 01K7Y3QD8M</p>
  <button class="btn btn--primary" type="button">Start over</button>
</div>
```

```html
<form class="upload" id="upload">
  <input type="file" id="eml" name="email" accept=".eml,message/rfc822">
  <label class="toggle"><input type="checkbox" id="contains-cid" checked>
    This email contains client identifying data</label>
  <button class="btn btn--primary" type="submit">Capture</button>
</form>
```

The CID checkbox is **checked by default** and is omitted entirely when the
server reports always-redact configuration (021 Part 2).

## Wide content

Only a table, a payload block or a diagram may exceed the pane width, each
inside its own `.scroll-x`. The page body never scrolls sideways.
