# ResidueTrace

ResidueTrace checks a narrow assertion: **does a declared rectangle in a PNG name the same observed polymer residue as the CSV row with its declared stable key?** The supplied static mmCIF is the authority for this identifier crosswalk. The output is a self-contained, clickable HTML report and a machine-readable JSON verdict. No network access is needed to audit a bundle.

## Run it

Use Python 3.11+ in a dedicated environment. From this directory in **Git Bash on Windows**:

```sh
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -e '.[test]'
residuetrace demo --out out/demo
```

On Linux/macOS use `source .venv/bin/activate` instead; on PowerShell use `.\.venv\Scripts\Activate.ps1`.

Open `out/demo/report.html` directly in a browser. Click a box to jump to its figure claim and then click the CSV line to see the original fields and independently resolved residue. `report.json` contains the same underlying evidence. The PNG is embedded; the report does not need a server, JavaScript, external fonts, or neighboring files. It includes all input CSV fields, so treat the report with the same care as the source data.

```sh
residuetrace audit src/residuetrace/demo/manifest.json --out out/audit
python -m residuetrace demo --out out/demo   # equivalent module entry point
python -m pytest -q                          # core checks and real-archive benchmark
```

The commands replace `report.json` and `report.html` in the chosen directory. Use a fresh destination to avoid confusing older output with a failed run. Exit codes: **0** all links verified, **1** report generated but not wholly verified, **2** unreadable/malformed input or unsuccessful output. Installation may require access to a package index; for offline installation, pre-stage compatible wheels for the project and its dependencies.

## Input v1

See the complete [working manifest](src/residuetrace/demo/manifest.json), [original teaching mmCIF](src/residuetrace/demo/teaching.cif), [PNG](src/residuetrace/demo/tiles.png), and [CSV](src/residuetrace/demo/claims.csv). **These are original synthetic teaching fixtures, not records from 3B9F or any other deposition.** The shapes are not a molecular rendering. In this exercise, model 1 **auth H:77A ↔ label B:73**; auth H:77 with no insertion instead maps to B:74. The same H:77A identifier occurs in model 2 and does not match a model-1 claim.

- UTF-8 JSON object with `schema_version: 1`, optional `description`, and `structure`, `figure`, `table` descriptors. Each descriptor contains a **relative local path within the manifest directory** and a 64-hex-digit `sha256` over the exact file bytes. No URLs. A changed newline changes the digest; do not repin merely to suppress a mismatch.
- `regions` is an array. An example entry is `{"id":"r1","rect":[12,16,40,24],"row_key":"k1","claim":{"model":1,"auth_asym_id":"H","auth_seq_id":"77","ins_code":"A"}}`. Integer rectangle coordinates are `[x,y,width,height]`, origin top left in the supplied PNG, with positive extent inside the image. Duplicate IDs or identical rectangles cannot verify. One region references one distinct key; repeated references cannot verify. Overlap by itself is not an identifier claim.
- UTF-8 CSV (BOM optional), distinct nonempty headers. Example: `row_key,model,label_asym_id,label_seq_id` followed by `k1,1,B,73`. Row order has no semantic meaning. Joins use exact, case-sensitive keys, never line numbers. Keyless or unlinked rows make the bundle non-green; duplicate keys are not resolved by choosing a row. Additional columns such as `note` are preserved literally, not interpreted.
- Both sources must supply their own claim. Each claim specifies **one** complete namespace and a positive model number: `model + label_asym_id + label_seq_id` (positive integer), or `model + auth_asym_id + auth_seq_id + ins_code` (author sequence identifier is an exact string). For auth claims an explicit empty string/empty CSV field means *no recorded insertion code*; omission is not a wildcard. IDs are not case-folded or trimmed; `.`, `?`, and surrounding whitespace are not valid declaration IDs. Numeric model/label sequence values may also be decimal strings. Mixed-namespace CSV tables may leave the inactive namespace columns empty. A missing model does not silently become model 1.

## What counts as observed

Gemmi reads one data block from uncompressed mmCIF. V1 requires `_entity.id,type` and the following `_atom_site` columns: `label_entity_id`, `label_asym_id`, `label_seq_id`, `label_comp_id`, `auth_asym_id`, `auth_seq_id`, `pdbx_PDB_ins_code`, `pdbx_PDB_model_num`, `Cartn_x`, `Cartn_y`, `Cartn_z`, `occupancy`. It joins the atom's declared entity ID to `_entity.type = polymer`; `ATOM` versus `HETATM` is not the filter. A site must have finite XYZ and finite positive occupancy. A sequence-scheme row or unobserved site never supplies evidence. Missing required columns, unresolved entity IDs, or incomplete identifiers in observed polymer sites are unsupported input, not permission to guess.

CIF null insertion tokens `.` / `?` both mean *no recorded code* for this crosswalk, not proof that an unrecorded insertion is biologically impossible. Repeated atoms/alternate locations with identical residue identifiers and component collapse into one observation. Distinct label components or inconsistent counterparts at the same address remain ambiguous. Both forward and reverse identifiers must resolve uniquely within the stated model, even if the two claims use the same namespace. Coordinates are used only as a presence check and are not emitted. V1 supports a single static PNG (up to 32 million pixels), not PDF, multi-panel inference, or animated images.

## Python / JSON contract

```python
from residuetrace import AuditError, audit

report = audit('src/residuetrace/demo/manifest.json')  # dict; no writes
assert report['schema_version'] == 1 and report['ok'] is True
region = report['regions'][0]
assert region['id'] == 'r1' and region['status'] == 'verified'
assert region['evidence']['figure']['candidates'][0]['ins_code'] == 'A'
line = region['evidence']['csv_lines'][0]
row = next(r for r in report['rows'] if r['line_start'] == line)
assert row['row_key'] == 'k1' and row['resolution']['candidates'][0]['label_seq_id'] == 73
```

`audit(path)` raises `AuditError` for unsupported or unreadable files. `report.files` records expected/actual SHA-256 and status per artifact. If any pin is missing, malformed, or does not match, the entire bundle is withheld before semantic parsing. `report.issues` lists bundle-level problems; each region carries `id`, `row_key`, `rect`, `status`, all applicable non-green reasons in `issues`, and `evidence`. `evidence.figure` and each CSV row's `resolution` carry the submitted `claim`, local `status`, and `candidates`. A candidate records model, both namespaces, insertion code, label entity/component, first 1-based `_atom_site` row, and observed atom-row count. CSV line spans are 1-based **physical lines including the header**, not join keys. `figure_size` is `[width,height]` or null for an untrusted bundle.

| Region status | Meaning |
|---|---|
| `verified` | Both declarations independently resolve to the same unique observed identifier; region and row binding valid. |
| `conflict` | Both declarations are legal and individually unique, but identify different residues (including different models). |
| `unknown` | No matching observed residue or no CSV row for the declared key. |
| `undeclared` | Missing/invalid claim, required ID/key, or integrity declaration. |
| `ambiguous` | At least one identifier does not have a unique crosswalk. |
| `duplicate` | Reused region identifier, rectangle, key reference, or duplicate CSV key. |
| `invalid_region` | Malformed or out-of-bounds rectangle. |
| `hash_mismatch` | At least one digest differs from its declaration; no region can verify. |

Use the **top-level `ok`** for an all-bundle gate; a valid region does not excuse an orphan CSV row. `verified` is agreement of supplied identifiers, **not** verification of what the pixels depict, authorship, experimental validity, function, sequence, or biological identity. This tool does not generate biological sequences, fetch archives, predict function, infer labels from images, or authenticate the external declarant. [Real-archive benchmark](benchmark/README.md) is maintained separately from the synthetic demo and core tests.

## Dependencies and licensing

Original core code, tests, and synthetic fixtures: [0BSD](LICENSE). No third-party deposition or figure is reproduced in the core demo. External files retain their own terms. Runtime: [Gemmi](https://github.com/project-gemmi/gemmi) (MPL-2.0) for mmCIF and [Pillow](https://python-pillow.org/) (MIT-CMU) for static PNG validation. [pytest](https://pytest.org/) (MIT) is test-only; setuptools is the build backend. Dependency licenses are not replaced by this project's license.
