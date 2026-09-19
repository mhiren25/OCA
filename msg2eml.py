#!/usr/bin/env python3
"""Convert Outlook .msg files (or a zip of them) to .eml.

    pip install extract-msg
    python msg2eml.py emails.zip -o inbox/
    python msg2eml.py path/to/msgs/ -o inbox/

WHAT YOU LOSE, AND WHY IT MATTERS

.msg does not contain the original MIME — Outlook stores a decomposed form.
So this RECONSTRUCTS an .eml rather than recovering one. Typically lost:

  - original Content-Transfer-Encoding  (rebuilt, not preserved)
  - original header order and some X- headers
  - the original charset, often normalised to UTF-8

That last one is the dangerous one for this project: a Japanese email that
arrived as ISO-2022-JP may come out as UTF-8, and your encoding fixture then
tests a case that never happens in production.

If the mail is still in Exchange, prefer the real thing:

    GET /v1.0/users/{user}/messages/{id}/$value      -> original MIME bytes

Use this script only when Graph is not available. Record in each fixture's
notes.md that it was converted from .msg, so a later encoding surprise is
traceable.

Alternative if you can't install extract-msg: msgconvert, from the Perl
package Email::Outlook::Message, which many estates already have.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import zipfile
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

try:
    import extract_msg
except ImportError:
    sys.exit("extract-msg not installed:  pip install extract-msg")


def to_eml(msg) -> bytes:
    """Prefer the library's own converter; fall back to building one."""
    # Recent extract-msg versions expose this and handle far more detail
    # than anything hand-rolled here.
    if hasattr(msg, "asEmailMessage"):
        try:
            return msg.asEmailMessage().as_bytes()
        except Exception as exc:  # noqa: BLE001 - fall through deliberately
            print(f"      asEmailMessage failed ({exc}), building manually", file=sys.stderr)

    em = EmailMessage()
    for header, value in (
        ("From", msg.sender),
        ("To", msg.to),
        ("Cc", msg.cc),
        ("Bcc", getattr(msg, "bcc", None)),
        ("Subject", msg.subject),
        ("Message-ID", getattr(msg, "messageId", None)),
    ):
        if value:
            em[header] = value

    if date := getattr(msg, "date", None):
        em["Date"] = format_datetime(date) if hasattr(date, "tzinfo") else str(date)

    em.set_content(msg.body or "")

    if html := getattr(msg, "htmlBody", None):
        # HTML matters: it carries the table structure that flattening destroys.
        text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
        em.add_alternative(text, subtype="html")

    for att in getattr(msg, "attachments", []):
        name = getattr(att, "longFilename", None) or getattr(att, "shortFilename", None) or "attachment"
        data = getattr(att, "data", None)
        if isinstance(data, bytes):
            em.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
        else:
            print(f"      skipped non-binary attachment {name!r}", file=sys.stderr)

    return em.as_bytes()


def convert(path: Path, out_dir: Path) -> bool:
    try:
        with extract_msg.openMsg(str(path)) as msg:
            eml = to_eml(msg)
    except Exception as exc:  # noqa: BLE001 - report and continue the batch
        print(f"  FAILED {path.name}: {exc}", file=sys.stderr)
        return False

    dst = out_dir / (path.stem + ".eml")
    n = 1
    while dst.exists():
        dst = out_dir / f"{path.stem}-{n}.eml"
        n += 1
    dst.write_bytes(eml)
    print(f"  {path.name} -> {dst.name}")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert Outlook .msg to .eml")
    ap.add_argument("source", help=".zip of .msg files, a directory, or a single .msg")
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    src = Path(args.source)

    with tempfile.TemporaryDirectory() as tmp:
        if src.suffix.lower() == ".zip":
            with zipfile.ZipFile(src) as z:
                z.extractall(tmp)
            files = sorted(Path(tmp).rglob("*.msg"))
        elif src.is_dir():
            files = sorted(src.rglob("*.msg"))
        else:
            files = [src]

        if not files:
            print("no .msg files found", file=sys.stderr)
            return 1

        print(f"{len(files)} file(s)\n")
        ok = sum(convert(f, args.out) for f in files)

    print(f"\n{ok}/{len(files)} converted -> {args.out}")
    print("\nNEXT: spot-check a converted file before trusting the batch —")
    print("  python -c \"from email import policy; from email.parser import BytesParser;\\")
    print("m=BytesParser(policy=policy.default).parsebytes(open('FILE.eml','rb').read());\\")
    print("b=m.get_body(('plain',)); print(m['Subject']); print(b.get_content_charset()); print(b.get_content()[:300])\"")
    print("\nCheck especially: is a non-English body still in its original charset,")
    print("or has it been normalised to UTF-8? Note the answer in notes.md.")
    return 0 if ok == len(files) else 2


if __name__ == "__main__":
    raise SystemExit(main())
