# `residuetrace resolve` — headless claim resolution

A scripting companion to the audit report: it resolves declared residue identifier claims, one JSON object per stdin line, against exactly one digest-pinned mmCIF structure and writes one JSON result per input line to stdout. It needs no figure, CSV, HTML, report files, service, model, or network access, and it reuses the same crosswalk semantics as `audit` — statuses and candidates come straight from the public implementation, without re-reading or re-parsing the structure per claim.

## One copyable command

From the repository root, with ResidueTrace installed in its dedicated environment (see the README):

```sh
printf '%s\n' '{"model":1,"auth_asym_id":"H","auth_seq_id":"77","ins_code":"A"}' | residuetrace resolve benchmark/data/3b9f.cif --sha256 4328a7037e6f7f852312e640bcd1d9839ab99b786a03edb9f38d5b958d714bbc
```

prints exactly one line and exits `0`:

```json
{"line": 1, "claim": {"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A"}, "status": "unique", "candidates": [{"model": 1, "auth_asym_id": "H", "auth_seq_id": "77", "ins_code": "A", "label_asym_id": "B", "label_seq_id": 73, "label_comp_id": "ARG", "label_entity_id": "2", "first_atom_site_row": 1, "observed_atom_rows": 2}], "structure_sha256": "4328a7037e6f7f852312e640bcd1d9839ab99b786a03edb9f38d5b958d714bbc"}
```

(The digest pins the shipped real-archive excerpt `benchmark/data/3b9f.cif`; recalculate it if you substitute your own structure file. `python -m residuetrace resolve …` is equivalent.)

## Input protocol (stdin)

- UTF-8 text; **one claim per line**, in the exact `Crosswalk.resolve` shape used by the manifest and CSV claims of `audit`: either `model` + `auth_asym_id` + `auth_seq_id` + `ins_code`, or `model` + `label_asym_id` + `label_seq_id`. An explicit empty `ins_code` means *no recorded insertion code* — it is not a wildcard. `model` and `label_seq_id` may be decimal strings. IDs are exact, never case-folded or trimmed; `?`, `.`, and padded values are not valid; a missing `model` is not defaulted to 1.
- Line numbers in results are 1-based **physical stdin lines**. Blank lines are protocol errors, not skips: every line must be one complete claim.
- A leading UTF-8 BOM on the first line and CRLF line endings are tolerated.

## Output protocol (stdout)

- Newline-delimited JSON, one object per successfully parsed input line, **in input order**, nothing else. Each object carries the input `line`, the echoed `claim`, the resolution `status`, the `candidates`, and the `structure_sha256` that binds every row to the exact structure bytes it was resolved against.
- `status` / `candidates` reuse the audit vocabulary: `unique`, `unknown`, `ambiguous`, `undeclared` — see the README ("Input v1" and "What counts as observed") for the full semantics. A candidate records model, both namespaces, insertion code, entity/component, and the first/observed `_atom_site` row counts. Ambiguity is reported, never guessed.
- stdout is ASCII-safe (non-ASCII characters are emitted as `\uXXXX` escapes), so console code pages cannot corrupt it; any JSON parser decodes them back. stderr carries diagnostics only.
- Each line is flushed as soon as it is resolved, so an interactive pipe client can read the reply before sending its next claim.

## Integrity binding

- `--sha256` is required and only a **matching** digest is accepted (uppercase hex is fine). The digest is computed over the exact structure file bytes — a changed newline changes it; do not repin merely to suppress a mismatch. On a mismatch nothing is resolved and stdout stays empty.
- The structure is parsed **exactly once** per invocation, regardless of how many claim lines follow.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Every input line resolved `unique` (and there was at least one). |
| `1` | No protocol errors, but at least one line is `unknown`, `ambiguous`, or `undeclared`. |
| `2` | Bad input or hash: missing/unreadable/unparsable structure; wrong or malformed `--sha256`; empty stdin; or any line that is not one JSON object — invalid JSON, a non-object value, duplicate JSON keys, `NaN`/`Infinity`, or invalid UTF-8. argparse usage errors also exit `2`. |

Diagnostics on exit 2 name the physical line number and quote the offending text. **Results stream as they resolve**: if line N is malformed, the replies for lines 1…N-1 have already been written to stdout before the diagnostic appears and the process exits 2. If a partial stream matters to your pipeline, consume stdout only after checking the exit code.

`undeclared` is deliberately a per-line resolution status (the JSON object is well-formed but does not name an identifier the way the crosswalk expects), while non-object lines, duplicate keys, and empty input are exit-2 protocol violations. Keeping the two apart means a downstream consumer can distinguish "the data did not declare this" from "the input stream itself was broken".

## Limitations

- Resolution is against observed polymer atom sites of the supplied file only; excerpt files must retain the `_entity` and `_atom_site` columns described in the README, and unobserved sites (zero occupancy, absent coordinates) supply no evidence.
- The pinned digest covers the structure file only; stdin claims are not separately authenticated, and the tool never validates who declared them.
- This checks identifier crosswalks only — not what any image depicts, authorship, experimental validity, sequence, function, or biological identity. It reads already-archived identifiers; it does not generate designs, fetch archives, predict anything, or run a model, and it emits no figures, CSV, or HTML.
