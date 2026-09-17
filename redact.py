#!/usr/bin/env python3
"""Redact client identifiers from .eml files, preserving everything else.

Two modes, and the order matters:

    scan    report what would be replaced. Changes nothing.
    apply   write redacted copies to an output directory.

Always scan first. Name detection in particular is unreliable, so scan
reports *candidates* for you to confirm or add to the config before anything
is rewritten.

WHAT IS PRESERVED, deliberately:
  - MIME structure, charsets, transfer encodings, quoting depth
  - Instruments, tickers, venues, quantities, prices
  - Boilerplate, disclaimers, banners, signatures, mangled tables
Noise and messiness are test inputs. A fixture that reads cleaner than the
email it came from is measuring an easier problem than the real one.

WHAT IS REPLACED:
  - Email addresses and display names  (consistent pseudonyms)
  - Account numbers, IBANs, phone numbers  (same shape and length)
  - The domain inside Message-ID  (its uniqueness is kept)

Pseudonyms are stable across the whole corpus, so a person who appears in
five emails is the same fake person in all five and threads still line up.

    python scripts/redact.py scan  inbox/*.eml
    python scripts/redact.py apply inbox/ -o corpus/staging/

THE MAPPING FILE IS THE RE-IDENTIFICATION KEY. It is written outside the
repository by default and must never be committed. Delete it once the corpus
is final and you no longer need stable pseudonyms for new arrivals.

This is a first pass, not the control. A human reads every redacted file
before it is committed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from pathlib import Path

DEFAULT_MAP = Path.home() / ".tca-redaction-map.json"

# --------------------------------------------------------------- patterns ---

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{2,4}(?![\w.])")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[\s-]?[A-Z0-9]{4}){2,7}[\s-]?[A-Z0-9]{1,4}\b")

# Account numbers vary by institution — override in redaction-patterns.json.
DEFAULT_ACCOUNT_PATTERNS = [
    r"\b\d{3}-\d{5}-\d{2}\b",
    r"\b[A-Z]{2}\d{8,12}\b",
    r"\b\d{9,14}\b",
]

# Candidates only. Never auto-replaced — surfaced in scan for you to confirm.
NAME_HINT_RE = re.compile(
    r"^[^\S\n]*(?:Dear|Hi|Hello|Regards|Thanks|Thks|Best|Kind regards)[,:]?"
    r"[^\S\n]+([A-Z][a-z]+(?:[^\S\n]+[A-Z][a-z]+)?)[^\S\n]*[,.]?[^\S\n]*$",
    re.MULTILINE,
)

FAKE_FIRST = ["Alex", "Jordan", "Sam", "Riley", "Casey", "Morgan", "Avery",
              "Quinn", "Reese", "Rowan", "Sage", "Blake", "Drew", "Ellis"]
FAKE_LAST = ["Hale", "Voss", "Rennick", "Marsh", "Calder", "Brandt", "Doyle",
             "Ferris", "Nash", "Okafor", "Petrov", "Sandoval", "Tanaka", "Weir"]

REDACT_HEADERS = ("From", "To", "Cc", "Bcc", "Reply-To", "Sender",
                  "Return-Path", "X-Original-To", "Delivered-To")


# ------------------------------------------------------------------ state ---

@dataclass
class Mapping:
    """Stable original → pseudonym assignments. The re-identification key."""

    path: Path
    emails: dict[str, str] = field(default_factory=dict)
    domains: dict[str, str] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    accounts: dict[str, str] = field(default_factory=dict)
    phones: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Mapping:
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return cls(path, d.get("emails", {}), d.get("domains", {}),
                       d.get("names", {}), d.get("accounts", {}), d.get("phones", {}))
        return cls(path)

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {"_warning": "RE-IDENTIFICATION KEY — never commit this file",
                 "emails": self.emails, "domains": self.domains,
                 "names": self.names, "accounts": self.accounts,
                 "phones": self.phones},
                indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
        self.path.chmod(0o600)

    # -- assignment -----------------------------------------------------------

    def domain_for(self, domain: str) -> str:
        if domain not in self.domains:
            self.domains[domain] = f"example{len(self.domains) + 1}.invalid"
        return self.domains[domain]

    def email_for(self, addr: str) -> str:
        addr = addr.lower()
        if addr not in self.emails:
            local, _, domain = addr.partition("@")
            n = len(self.emails) + 1
            # keep local-part length so alignment and wrapping behave the same
            fake_local = f"user{n:03d}"[: max(4, len(local))].ljust(len(local), "x")
            self.emails[addr] = f"{fake_local}@{self.domain_for(domain)}"
        return self.emails[addr]

    def name_for(self, name: str) -> str:
        """One person, one pseudonym — however they are written.

        "Frank Tso" in a header and "Frank" in a sign-off are the same person,
        and giving them different fake identities would make the corpus lie
        about who sent what. So a bare first name reuses the first name of an
        already-mapped full name, and vice versa.

        List full names before short forms in the config; they are applied
        longest-first, so the full name is mapped and the short form inherits.
        """
        key = name.strip()
        if key in self.names:
            return self.names[key]

        first_token = key.split()[0]
        for existing, pseudo in self.names.items():
            tokens, pseudo_tokens = existing.split(), pseudo.split()
            if tokens[0] == first_token:
                # bare "Frank" after "Frank Tso" -> "Alex"
                self.names[key] = (pseudo_tokens[0] if len(key.split()) == 1
                                   else pseudo)
                return self.names[key]
            if len(tokens) == 1 and tokens[0] == key.split()[0]:
                self.names[key] = pseudo
                return self.names[key]

        n = len([k for k in self.names if " " in k] or self.names)
        first = FAKE_FIRST[len(self.names) % len(FAKE_FIRST)]
        if " " in key:
            last = FAKE_LAST[(len(self.names) // len(FAKE_FIRST)) % len(FAKE_LAST)]
            self.names[key] = f"{first} {last}"
        else:
            self.names[key] = first
        return self.names[key]

    def account_for(self, acct: str) -> str:
        if acct not in self.accounts:
            n = len(self.accounts) + 1
            # same length, same shape — parsing behaviour must not change
            digits = f"{n:0{sum(c.isdigit() for c in acct)}d}"
            it = iter(digits)
            self.accounts[acct] = "".join(
                next(it, "0") if c.isdigit() else ("X" if c.isalpha() else c)
                for c in acct)
        return self.accounts[acct]

    def phone_for(self, phone: str) -> str:
        if phone not in self.phones:
            n = len(self.phones) + 1
            digits = f"{n:0{sum(c.isdigit() for c in phone)}d}"
            it = iter(digits)
            self.phones[phone] = "".join(
                next(it, "0") if c.isdigit() else c for c in phone)
        return self.phones[phone]


# ------------------------------------------------------------- redaction ---

@dataclass
class Report:
    counts: Counter[str] = field(default_factory=Counter)
    name_candidates: Counter[str] = field(default_factory=Counter)
    samples: dict[str, set[str]] = field(default_factory=dict)

    def hit(self, kind: str, value: str) -> None:
        self.counts[kind] += 1
        self.samples.setdefault(kind, set()).add(value)


SENTINEL = "\x00TCA{}\x00"


def redact_text(text: str, m: Mapping, patterns: list[re.Pattern[str]],
                names: list[str], rep: Report, *, apply: bool) -> str:
    """Each match is parked behind a sentinel as soon as it is found.

    Without this the passes cascade: an email address is replaced, then the
    phone pattern matches digits inside the replacement, then the account
    pattern matches digits inside *that*. Parking a match makes it invisible
    to every later pattern, and the sentinels are swapped back at the end.

    Order is most-specific first for the same reason: 812-44902-11 is an
    account number, and only looks like a phone number once the account
    pattern has been denied its turn.
    """
    parked: list[str] = []

    def park(value: str) -> str:
        parked.append(value)
        return SENTINEL.format(len(parked) - 1)

    def replacer(kind: str, resolve):
        def _sub(match: re.Match[str]) -> str:
            original = match.group(0)
            rep.hit(kind, original)
            return park(resolve(original) if apply else original)
        return _sub

    text = EMAIL_RE.sub(replacer("email", m.email_for), text)
    text = IBAN_RE.sub(replacer("iban", m.account_for), text)
    for pat in patterns:
        text = pat.sub(replacer("account", m.account_for), text)
    text = PHONE_RE.sub(replacer("phone", m.phone_for), text)

    # Confirmed names only — longest first so "Peng Bao" wins over "Peng".
    for name in sorted(names, key=len, reverse=True):
        pattern = re.compile(rf"\b{re.escape(name)}\b")
        if pattern.search(text):
            text = pattern.sub(replacer("name", m.name_for), text)

    for match in NAME_HINT_RE.finditer(text):
        candidate = match.group(1).strip()
        if candidate and candidate not in names:
            rep.name_candidates[candidate] += 1

    for i, value in enumerate(parked):
        text = text.replace(SENTINEL.format(i), value)
    return text


def redact_message(msg: EmailMessage, m: Mapping, patterns: list[re.Pattern[str]],
                   names: list[str], rep: Report, *, apply: bool) -> None:
    for header in REDACT_HEADERS:
        for i, raw in enumerate(msg.get_all(header, [])):
            new = redact_text(str(raw), m, patterns, names, rep, apply=apply)
            if apply and new != str(raw):
                values = msg.get_all(header)
                del msg[header]
                for j, v in enumerate(values):
                    msg[header] = new if j == i else v

    if subject := msg.get("Subject"):
        new = redact_text(str(subject), m, patterns, names, rep, apply=apply)
        if apply and new != str(subject):
            del msg["Subject"]
            msg["Subject"] = new

    # Keep the unique part of Message-ID (it is the dedup key), replace the
    # domain that identifies the sender.
    if mid := msg.get("Message-ID"):
        if match := re.search(r"@([\w.-]+)>?\s*$", str(mid)):
            rep.hit("message-id-domain", match.group(1))
            if apply:
                new = str(mid).replace(match.group(1), m.domain_for(match.group(1)))
                del msg["Message-ID"]
                msg["Message-ID"] = new

    for part in msg.walk():
        if part.get_content_maintype() != "text":
            continue
        try:
            body = part.get_content()
        except (LookupError, UnicodeDecodeError) as exc:
            print(f"    ! undecodable part ({exc}) — left untouched", file=sys.stderr)
            continue
        new = redact_text(body, m, patterns, names, rep, apply=apply)
        if apply and new != body:
            charset = part.get_content_charset() or "utf-8"
            cte = part.get("Content-Transfer-Encoding", "quoted-printable")
            subtype = part.get_content_subtype()
            part.set_content(new, subtype=subtype, charset=charset, cte=cte)


# ------------------------------------------------------------------- main ---

def load_config(path: Path | None) -> tuple[list[re.Pattern[str]], list[str]]:
    patterns, names = DEFAULT_ACCOUNT_PATTERNS, []
    if path and path.exists():
        cfg = json.loads(path.read_text(encoding="utf-8"))
        patterns = cfg.get("account_patterns", patterns)
        names = cfg.get("names", [])
    return [re.compile(p) for p in patterns], names


def gather(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        out.extend(sorted(path.rglob("*.eml")) if path.is_dir() else [path])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Redact client identifiers from .eml")
    ap.add_argument("mode", choices=["scan", "apply"])
    ap.add_argument("paths", nargs="+", help=".eml files or directories")
    ap.add_argument("-o", "--out", type=Path, help="output dir (apply only)")
    ap.add_argument("-c", "--config", type=Path,
                    default=Path("scripts/redaction-patterns.json"))
    ap.add_argument("--map", type=Path, default=DEFAULT_MAP,
                    help=f"pseudonym map, kept outside the repo (default {DEFAULT_MAP})")
    args = ap.parse_args(argv)

    if args.mode == "apply" and not args.out:
        ap.error("apply needs -o/--out. The originals are never modified.")

    patterns, names = load_config(args.config)
    mapping = Mapping.load(args.map)
    rep = Report()
    files = gather(args.paths)
    if not files:
        print("no .eml files found", file=sys.stderr)
        return 1

    apply = args.mode == "apply"
    if apply:
        args.out.mkdir(parents=True, exist_ok=True)

    for src in files:
        msg = BytesParser(policy=policy.default).parsebytes(src.read_bytes())
        redact_message(msg, mapping, patterns, names, rep, apply=apply)
        if apply:
            dst = args.out / src.name
            dst.write_bytes(msg.as_bytes())
            print(f"  {src.name} → {dst}")

    if apply:
        mapping.save()

    print(f"\n{len(files)} file(s), mode={args.mode}\n")
    for kind, n in sorted(rep.counts.items()):
        shown = sorted(rep.samples.get(kind, set()))[:3]
        print(f"  {kind:<20} {n:>4}   e.g. {', '.join(shown)}")

    if rep.name_candidates:
        print("\n  Possible names NOT replaced — names cannot be detected reliably.")
        print("  Confirm these and add them to the config's \"names\" list:\n")
        for name, n in rep.name_candidates.most_common(20):
            print(f"      {name!r}  ({n}x)")
        print(f"\n  {args.config}:  {{\"names\": [\"Frank\", \"Esther\", ...]}}")

    if apply:
        print(f"\n  map → {mapping.path}  (0600, re-identification key, never commit)")
    print("\n  A human reads every redacted file before it is committed.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
