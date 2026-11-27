"""Load a pinned local bundle, then compare figure and table claims by stable key."""

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from .structure import CLAIM_FIELDS, AuditError, identifier, read_crosswalk


def _object(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise AuditError("duplicate manifest field")
    return obj


def _finite_number(token):
    number = float(token)
    if not math.isfinite(number):
        raise AuditError(f"non-finite JSON number: {token}")
    return number


def _files(manifest, root):
    info, content, paths = {}, {}, set()
    for name in ("structure", "figure", "table"):
        spec = manifest.get(name, {})
        if not isinstance(spec, dict):
            raise AuditError(f"{name}: expected file descriptor object")
        path, expected = spec.get("path"), spec.get("sha256")
        actual, status = None, "undeclared"
        if isinstance(path, str) and path:
            if Path(path).anchor:
                raise AuditError(f"{name}: expected a relative local path")
            dest = (root / path).resolve()
            if not dest.is_relative_to(root):
                raise AuditError(f"{name}: path must be relative and inside the manifest directory")
            paths.add(dest)
            data = dest.read_bytes()
            actual = hashlib.sha256(data).hexdigest()
            if isinstance(expected, str) and re.fullmatch(r"[0-9a-fA-F]{64}", expected):
                status = "matched" if actual == expected.lower() else "hash_mismatch"
                if status == "matched":
                    content[name] = data
        info[name] = {"path": path, "sha256": expected, "actual_sha256": actual, "status": status}
    return info, content, paths


def _dimensions(data):
    with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
        if image.n_frames != 1 or image.width * image.height > 32_000_000:
            raise AuditError("figure: expected one static PNG frame (maximum 32 MP)")
        image.verify()
        size = image.size
    with Image.open(io.BytesIO(data), formats=["PNG"]) as image:
        image.load()
    return size


def _read_rows(data, index):
    reader = csv.reader(io.StringIO(data.decode("utf-8-sig"), newline=""), strict=True)
    headers = next(reader, [])
    if not headers or not all(headers) or len(set(headers)) != len(headers):
        raise AuditError("table: expected a nonempty header with distinct column names")
    rows = []
    while True:
        start = reader.line_num + 1
        cells = next(reader, None)
        if cells is None:
            return rows
        if not cells:
            continue
        if len(cells) != len(headers):
            raise AuditError(f"table line {start}: field count differs from header")
        fields = dict(zip(headers, cells))
        claim = {k: v for k, v in fields.items() if k in CLAIM_FIELDS and v != ""}
        if "ins_code" in fields and ("auth_asym_id" in claim or "auth_seq_id" in claim):
            claim["ins_code"] = fields["ins_code"]
        rows.append({"line_start": start, "line_end": reader.line_num, "row_key": fields.get("row_key"),
                     "fields": fields, "resolution": index.resolve(claim)})


def valid_rect(rect, size):
    if not isinstance(rect, list) or len(rect) != 4 or not all(type(n) is int for n in rect):
        return False
    x, y, w, h = rect
    return x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= size[0] and y + h <= size[1]


def _evaluate(path):
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_object,
                          parse_constant=_finite_number, parse_float=_finite_number)
    if not isinstance(manifest, dict) or type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise AuditError("expected manifest schema_version 1")
    regions = manifest.get("regions", [])
    if not isinstance(regions, list) or not all(isinstance(r, dict) for r in regions):
        raise AuditError("regions must be an array of objects")
    files, data, protected = _files(manifest, path.parent)
    issues = [{"status": f["status"], "file": k} for k, f in files.items() if f["status"] != "matched"]
    blocked = {i["status"] for i in issues}
    index = size = png = None
    rows = []
    if not blocked:  # Never interpret or render a bundle with a broken integrity binding.
        index = read_crosswalk(data["structure"])
        png = data["figure"]
        size = _dimensions(png)
        rows = _read_rows(data["table"], index)
    by_key = defaultdict(list)
    for row in rows:
        by_key[row["row_key"]].append(row)
    ids, keys = (Counter(r[k] for r in regions if identifier(r.get(k))) for k in ("id", "row_key"))
    boxes = Counter(tuple(r["rect"]) for r in regions if size and valid_rect(r.get("rect"), size))
    if not regions:
        issues.append({"status": "undeclared", "detail": "no figure regions declared"})
    for key, group in by_key.items():
        lines = [r["line_start"] for r in group]
        if not identifier(key) or key not in keys:
            issues.append({"status": "undeclared", "detail": "row has no matching region", "row_key": key, "csv_lines": lines})
        if len(group) > 1:
            issues.append({"status": "duplicate", "detail": "duplicate CSV row_key", "row_key": key, "csv_lines": lines})

    results = []
    for region in regions:
        rid, key, rect, claim = (region.get(k) for k in ("id", "row_key", "rect", "claim"))
        matches = by_key.get(key, []) if identifier(key) else []
        figure = index.resolve(claim) if index is not None else {"claim": claim, "status": "not_checked", "candidates": []}
        reasons = []
        if blocked:
            reasons = sorted(blocked)  # hash_mismatch takes precedence over undeclared
        else:
            if not identifier(rid) or not identifier(key):
                reasons.append("undeclared")
            if not valid_rect(rect, size):
                reasons.append("invalid_region")
            elif boxes[tuple(rect)] > 1:
                reasons.append("duplicate")
            if (identifier(rid) and ids[rid] > 1) or (identifier(key) and keys[key] > 1) or len(matches) > 1:
                reasons.append("duplicate")
            if identifier(key) and not matches:
                reasons.append("unknown")
            resolutions = [figure, *(r["resolution"] for r in matches)]
            reasons.extend(c["status"] for c in resolutions if c["status"] != "unique")
            if len(matches) == 1 and all(c["status"] == "unique" for c in resolutions):
                if figure["candidates"] != matches[0]["resolution"]["candidates"]:
                    reasons.append("conflict")
        results.append({"id": rid, "row_key": key, "rect": rect, "status": next(iter(reasons), "verified"),
                        "issues": list(dict.fromkeys(reasons)),
                        "evidence": {"figure": figure, "csv_lines": [r["line_start"] for r in matches]}})
    report = {"schema_version": 1, "ok": not issues and all(r["status"] == "verified" for r in results),
              "description": manifest.get("description", ""), "files": files, "issues": issues,
              "figure_size": list(size) if size else None, "regions": results, "rows": rows}
    return report, png, protected | {path}


def evaluate(path):
    try:
        return _evaluate(path)
    except AuditError:
        raise
    except (OSError, ValueError, csv.Error, Image.DecompressionBombError, SyntaxError) as exc:
        raise AuditError(str(exc)) from exc


def audit(manifest_path):
    """Return a JSON-serializable v1 verdict; never fetch data or write files."""
    return evaluate(manifest_path)[0]
