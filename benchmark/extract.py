"""Rebuild the shipped excerpts from separately downloaded wwPDB mmCIF data."""

import argparse
import gzip
import hashlib
from pathlib import Path

import gemmi

# Match uncompressed files so changes in gzip metadata do not invalidate a source.
SOURCES = {
    "1CRN": ("23787562c427d7c1abe5420e86d5f1d0a6c7007dec1e8ce85645a6d69c32e8ba", {"41", "49", "56"}),
    "3B9F": ("740ba47bc186122a5e9dfc45f0ef18b87c5d6a39c7e95f0f7369540980359ed4", {"1035", "1036", "1057", "1058", "1072"}),
}


def extract(source: Path, out: Path) -> None:
    with gzip.open(source, "rb") as f:
        raw = f.read()
    block = gemmi.cif.read_string(raw).sole_block()
    digest, ids = SOURCES[block.name.upper()]
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("Unexpected archive revision; review the evidence before updating")
    doc = gemmi.cif.Document()
    excerpt = doc.add_new_block(block.name + "_excerpt")
    atoms = block.find_mmcif_category("_atom_site.")
    tags = list(atoms.tags)
    id_col = tags.index("_atom_site.id")
    entity_col = tags.index("_atom_site.label_entity_id")
    kept = [list(row) for row in atoms if row[id_col] in ids]
    if {r[id_col] for r in kept} != ids:
        raise ValueError("Missing archive rows")
    entity_ids = {r[entity_col] for r in kept}
    entities = excerpt.init_loop("_entity.", ["id", "type"])
    for eid, kind in block.find("_entity.", ["id", "type"]):
        if eid in entity_ids:
            entities.add_row([eid, kind])
    loop = excerpt.init_loop("", tags)
    for row in kept:
        loop.add_row(row)
    with out.open("x", encoding="ascii", newline="\n") as f:
        f.write(doc.as_string())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Original .cif.gz file")
    parser.add_argument("out", type=Path, help="New local excerpt file")
    args = parser.parse_args()
    extract(args.source, args.out)
