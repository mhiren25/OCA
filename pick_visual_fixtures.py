#!/usr/bin/env python3
"""Pick the visual test set for change 021.

Read-only. Writes nothing, touches nothing under corpus/.
Run from the repo root:  python3 pick_visual_fixtures.py

Prints what it measured so you can sanity-check the picks rather than
trusting them. Final choice is yours — ties and judgement calls are the
point of eyeballing the table.
"""

from __future__ import annotations

import json
import pathlib
import sys

FIXTURES = pathlib.Path("corpus/fixtures")


def count_unresolved(node) -> int:
    """Count tri-state fields whose state is Unresolved, at any depth."""
    n = 0
    if isinstance(node, dict):
        if node.get("state") == "Unresolved":
            n += 1
        for v in node.values():
            n += count_unresolved(v)
    elif isinstance(node, list):
        for v in node:
            n += count_unresolved(v)
    return n


def read_tags(d: pathlib.Path) -> list[str]:
    """Tags out of label.yaml without a yaml dependency."""
    f = d / "label.yaml"
    if not f.exists():
        return []
    tags: list[str] = []
    in_block = False
    for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("tags:"):
            in_block = True
            rest = stripped[5:].strip()
            if rest.startswith("["):
                return [t.strip().strip("'\"") for t in rest.strip("[]").split(",") if t.strip()]
            continue
        if in_block:
            if stripped.startswith("- "):
                tags.append(stripped[2:].strip().strip("'\""))
            elif stripped and not line.startswith((" ", "\t")):
                break
    return tags


def email_shape(d: pathlib.Path) -> tuple[int, int]:
    """(total lines, bytes) of the source email, whatever it is called."""
    for pat in ("*.eml", "*.txt", "email.*", "source.*"):
        for f in sorted(d.glob(pat)):
            if f.is_file():
                text = f.read_text(encoding="utf-8", errors="replace")
                return len(text.splitlines()), len(text.encode("utf-8"))
    return 0, 0


def main() -> int:
    if not FIXTURES.is_dir():
        print(f"no {FIXTURES} — run this from the repo root", file=sys.stderr)
        return 1

    rows = []
    for d in sorted(p for p in FIXTURES.iterdir() if p.is_dir()):
        exp = d / "expected.capture.json"
        if not exp.exists():
            continue
        try:
            data = json.loads(exp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"  ! {d.name}: unreadable expected.capture.json ({e})", file=sys.stderr)
            continue

        orders = data.get("lines") or data.get("orders") or []
        n_lines = len(orders) if isinstance(orders, list) else 0
        n_unres = count_unresolved(data)
        per_order = (n_unres / n_lines) if n_lines else 0.0
        email_lines, email_bytes = email_shape(d)
        tags = read_tags(d)

        rows.append({
            "id": d.name,
            "orders": n_lines,
            "unresolved": n_unres,
            "unres_per_order": per_order,
            "email_lines": email_lines,
            "email_bytes": email_bytes,
            "tags": tags,
        })

    if not rows:
        print("found no fixtures with an expected.capture.json", file=sys.stderr)
        return 1

    w = max(len(r["id"]) for r in rows)
    print(f"\n{'fixture':<{w}}  orders  unres  per-order  eml-lines  eml-bytes  tags")
    print("-" * (w + 62))
    for r in sorted(rows, key=lambda r: -r["orders"]):
        print(
            f"{r['id']:<{w}}  {r['orders']:>6}  {r['unresolved']:>5}  "
            f"{r['unres_per_order']:>9.1f}  {r['email_lines']:>9}  "
            f"{r['email_bytes']:>9}  {','.join(r['tags'][:6])}"
        )

    def top(key):
        return max(rows, key=lambda r: r[key])

    non_english = [r for r in rows if any("non-english" in t or "non_english" in t for t in r["tags"])]

    print("\n--- candidates ---")
    print(f"widest    (most orders)          {top('orders')['id']}  "
          f"({top('orders')['orders']} orders)")
    print(f"longest   (most email lines)     {top('email_lines')['id']}  "
          f"({top('email_lines')['email_lines']} lines)")
    print(f"emptiest  (unresolved per order) {top('unres_per_order')['id']}  "
          f"({top('unres_per_order')['unres_per_order']:.1f} per order)")
    print(f"non-english                      "
          f"{non_english[0]['id'] if non_english else 'NONE TAGGED — coverage gap'}")
    print("\nCheck these against the table above before writing them into 021.")
    print("'longest' in particular: most lines is not always the most boilerplate")
    print("around the shortest live region, which is the case that stresses the pane.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
