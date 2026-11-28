"""Streaming stdin-to-stdout resolution of declared residue identifier claims.

A non-interactive companion to the audit report: one JSON claim per stdin line
is resolved against one digest-pinned structure and one JSON result per line is
written to stdout in input order. No figures, CSV, HTML, services, or models.
"""

import hashlib
import json
import math
import re
import sys
from pathlib import Path

from .structure import AuditError, read_crosswalk

SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
CONTEXT_LIMIT = 200


class InputError(ValueError):
    """A stdin line (or the absence of one) violates the claim-line protocol."""


def _pairs(pairs):
    seen = set()
    for key, _ in pairs:
        if key in seen:
            raise InputError(f"duplicate JSON field {key!r}")
        seen.add(key)
    return dict(pairs)


def _finite(token):
    number = float(token)
    if not math.isfinite(number):
        raise InputError(f"non-finite JSON number: {token}")
    return number


def _constant(name):
    raise InputError(f"non-finite JSON literal: {name}")


def _decode(raw, number):
    if isinstance(raw, str):
        text = raw
    else:
        try:
            text = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise InputError(f"line {number}: not valid UTF-8 ({exc.reason})") from exc
    if number == 1:
        text = text.removeprefix("\ufeff")  # tolerate a byte-order mark like other UTF-8 inputs
    return text


def _claim(text, number):
    try:
        claim = json.loads(text, object_pairs_hook=_pairs, parse_float=_finite, parse_constant=_constant)
    except InputError as exc:
        raise InputError(f"line {number}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"line {number}: invalid JSON at column {exc.colno}: {exc.msg}") from exc
    if not isinstance(claim, dict):
        raise InputError(f"line {number}: expected a JSON object, got {type(claim).__name__}")
    return claim


def resolve_stream(index, instream, out, digest):
    """Write one JSON result per valid claim line, in input order; True when every status is unique."""
    lines = 0
    unresolved = False
    for number, raw in enumerate(instream, 1):
        lines = number
        text = _decode(raw, number)
        try:
            claim = _claim(text, number)
        except InputError as exc:
            shown = text if len(text) <= CONTEXT_LIMIT else text[:CONTEXT_LIMIT] + "..."
            raise InputError(f"{exc} [input: {shown!r}]") from exc
        result = index.resolve(claim)
        unresolved |= result["status"] != "unique"
        record = {"line": number, **result, "structure_sha256": digest}
        out.write(json.dumps(record, ensure_ascii=True).encode('ascii') + b'\n')
        out.flush()  # A pipe client can read this row before sending its next claim.
    if not lines:
        raise InputError("empty input: expected at least one claim line")
    return not unresolved


def run(args, instream=None, out=None):
    """Verify the pinned digest, parse the structure exactly once, stream results.

    Returns 0 when every claim resolved unique, 1 when some line is unresolved,
    and 2 for any digest, structure, or stdin protocol violation.
    """
    try:
        if not SHA256.fullmatch(args.sha256):
            raise InputError("--sha256 must be 64 hexadecimal digits")
        data = args.structure.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != args.sha256.lower():
            raise InputError(f"structure sha256 mismatch: expected {args.sha256.lower()}, actual {digest}")
        index = read_crosswalk(data)  # parsed once per invocation, never per claim
        if instream is None:
            instream = sys.stdin.buffer
        if out is None:
            out = sys.stdout.buffer
        return 0 if resolve_stream(index, instream, out, digest) else 1
    except (InputError, AuditError, OSError) as exc:
        print(f"residuetrace: {exc}", file=sys.stderr)
        return 2


def add_parser(subparsers):
    resolve = subparsers.add_parser('resolve',
                                    help='resolve identifier claims from stdin against a digest-pinned structure')
    resolve.add_argument('structure', type=Path, help='local mmCIF structure file')
    resolve.add_argument('--sha256', required=True, metavar='SHA',
                         help='expected sha256 over the exact structure bytes (64 hex digits)')
    return resolve
