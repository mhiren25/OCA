#!/usr/bin/env python3
"""Generate corpus/schema/capture.v1.schema.json from the Pydantic models.

    python scripts/gen_schema.py                 # write it
    python scripts/gen_schema.py --stdout        # preview, write nothing
    python scripts/gen_schema.py --validate      # then check every fixture against it

The schema is committed so fixtures can be validated without importing the
package, and so a schema change shows up in review rather than arriving
silently with a code change. `corpus/schema/` is CODEOWNERS-protected for the
same reason: a schema change invalidates labels.

WHY --validate MATTERS MORE THAN THE SCHEMA

`build_fixture.py` writes the capture shape by hand. The models define it in
code. Those two can drift, and nothing catches it until an eval compares a
model output against a fixture and the mismatch is read as a scoring failure
rather than a shape failure. Run --validate the first time and after any
change to either side; a fixture that will not validate is a fixture that
cannot be scored, however carefully it was labelled.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import pkgutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "corpus" / "schema" / "capture.v1.schema.json"

# Most likely first. The agent that built 001 chose these names, not us, so
# search rather than assume — and report what was found either way.
PREFERRED = ("CaptureModel", "Capture", "CaptureEnvelope", "CaptureResult")


def find_model():
    """Locate the top-level capture model without knowing what 001 called it."""
    try:
        from pydantic import BaseModel
    except ImportError:
        sys.exit("pydantic not installed — activate the venv first (source .venv/bin/activate)")

    sys.path.insert(0, str(REPO / "src"))
    try:
        domain = importlib.import_module("trade_capture.domain")
    except ImportError as exc:
        sys.exit(f"cannot import trade_capture.domain ({exc}). Is 001 built, and the venv active?")

    found: dict[str, type] = {}
    modules = [domain]
    if hasattr(domain, "__path__"):
        for m in pkgutil.iter_modules(domain.__path__):
            try:
                modules.append(importlib.import_module(f"trade_capture.domain.{m.name}"))
            except ImportError:
                continue

    for mod in modules:
        for name, obj in vars(mod).items():
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel:
                found.setdefault(name, obj)

    if not found:
        sys.exit("no Pydantic models found under trade_capture.domain")

    for name in PREFERRED:
        if name in found:
            return name, found[name]

    sys.exit("could not tell which model is the top-level capture type.\n"
             "Candidates: " + ", ".join(sorted(found)) +
             "\nEdit PREFERRED in this script to name the right one.")


def validate(schema: dict) -> int:
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("jsonschema not installed — skipping validation "
              "(pip install jsonschema)", file=sys.stderr)
        return 0

    validator = Draft202012Validator(schema)
    fixtures = sorted((REPO / "corpus" / "fixtures").glob("*/expected.capture.json"))
    if not fixtures:
        print("no fixtures to validate")
        return 0

    bad = 0
    for f in fixtures:
        doc = json.loads(f.read_text(encoding="utf-8"))
        # Keys we add for humans, which the model does not have.
        doc = {k: v for k, v in doc.items() if not k.startswith("_")}
        errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
        if errors:
            bad += 1
            print(f"\n  {f.parent.name}: {len(errors)} problem(s)")
            for e in errors[:5]:
                where = ".".join(str(p) for p in e.path) or "(root)"
                print(f"      {where}: {e.message[:140]}")

    if bad:
        print(f"\n{bad}/{len(fixtures)} fixtures do not match the model.\n"
              "Either build_fixture.py writes the wrong shape or the model changed. "
              "Fix whichever is wrong — do NOT loosen the schema to make this pass.")
        return 2
    print(f"{len(fixtures)}/{len(fixtures)} fixtures validate against the model.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pydantic models -> capture.v1.schema.json")
    ap.add_argument("--stdout", action="store_true", help="print, write nothing")
    ap.add_argument("--validate", action="store_true", help="check fixtures against it")
    args = ap.parse_args(argv)

    name, model = find_model()
    schema = model.model_json_schema()
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    schema["title"] = "capture.v1"
    text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"

    if args.stdout:
        print(text)
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8")
        print(f"{name} -> {OUT.relative_to(REPO)}  ({len(text)} bytes)")

    return validate(schema) if args.validate else 0


if __name__ == "__main__":
    raise SystemExit(main())
