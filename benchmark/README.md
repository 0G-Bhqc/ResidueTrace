# Real-archive identifier benchmark

Can a figure annotation and a table row both contain valid residue IDs yet refer to different residues? This small diagnostic has 12 cases: six on **1CRN** (development) and six on **3B9F** (test). The figure is an original schematic, not a deposition image or a molecular rendering. The supplied claims and errors are constructed; **only the reference atom records come from the actual archive**. There is no network access or model download at evaluation time.

## Reproduce

From the repository root, with ResidueTrace installed:

```sh
python benchmark/evaluate.py prepare out/bench-v1  # destination must not exist
python benchmark/evaluate.py run out/bench-v1 --split test --baseline literal
python benchmark/evaluate.py run out/bench-v1 --split test --baseline mapped
python -m pytest -q tests benchmark/test_evaluate.py
```

Expected correct counts on these fixed examples:

| Split | Items | Literal string comparison | mmCIF crosswalk |
|---|---:|---:|---:|
| 1CRN (dev) | 6 | 6 | 6 |
| 3B9F (test) | 6 | 4 | 6 |

Both failures of the literal rule on 3B9F are false conflicts. For example, the deposited records equate model 1 author `H:77` with insertion `A` to label `B:73`; `B:74` also exists but designates a different residue. The script creates a positive and a negative with identical images, regions and figure claims, changing only the residue stated by the selected table row. In the third condition the figure annotation lacks its chain identifier: do not guess even if the excerpt is small. Each split contains two items of each class. `mapped` invokes the installed **public `residuetrace.audit` implementation**. `literal` checks declaration completeness and compares the printed chain, number and insertion code without a crosswalk.

To evaluate an external system, give it only the chosen split's manifests and input files from `index.json`. Ask: *Do the declared region and its referenced row identify the same observed residue?* Write a JSON object mapping every item ID in that split to `consistent`, `conflict`, or `insufficient`, then run `python benchmark/evaluate.py run out/bench-v1 --split test --predictions answers.json`. The scorer rejects missing, extra, duplicate or unknown responses and reports correct/total per class. Keep `gold.json` out of model inputs. The labels are public for reproducibility, not a blind leaderboard. The two structures do not overlap across splits, but two structures and templated questions **cannot establish model generalization or image recognition**.

## Data provenance

The small excerpts in `data/` are incomplete mmCIF blocks. They retain selected original `_atom_site` rows (including alternate locations) and the corresponding `_entity.id/type`. They must not be used as full structures. Data files are from the wwPDB archive under [CC0 1.0](https://www.wwpdb.org/about/usage-policies); the software license does not change those terms. No publisher or RCSB website images are included. Please credit the original depositions and publications:

| Entry (source) | Archive revision date | Atom IDs retained | Structure publication |
|---|---|---|---|
| [1CRN](https://www.rcsb.org/structure/1CRN) · [archive file](https://files.rcsb.org/download/1CRN.cif.gz) | 2024-10-30 | 41, 49, 56 | [DOI](https://doi.org/10.1073/pnas.81.19.6014) |
| [3B9F](https://www.rcsb.org/structure/3B9F) · [archive file](https://files.rcsb.org/download/3B9F.cif.gz) | 2024-11-06 | 1035, 1036, 1057, 1058, 1072 | [DOI](https://doi.org/10.1073/pnas.0711055105) |

Optional verification: download the original `.cif.gz` file into a new directory, then from the repository root run `python -I benchmark/extract.py PATH/TO/3B9F.cif.gz NEW-EXCERPT.cif`. The extractor pins the SHA-256 of the **uncompressed** snapshot and refuses a revised archive or an existing destination. Excerpts were generated with Gemmi 0.7.5. Original figures and benchmark code fall under the repository's [0BSD license](../LICENSE).
