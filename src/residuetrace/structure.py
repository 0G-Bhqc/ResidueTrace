"""Model-scoped identifier crosswalk from observed polymer atom sites only."""

import gzip
import io
import math
import re
import zlib
from collections import defaultdict
from dataclasses import asdict, dataclass

import gemmi


class AuditError(ValueError):
    """Input could not be read unambiguously as a supported file format."""


AUTH = {"auth_asym_id", "auth_seq_id", "ins_code"}
LABEL = {"label_asym_id", "label_seq_id"}
CLAIM_FIELDS = AUTH | LABEL | {"model"}
ATOM_TAGS = ("label_entity_id label_asym_id label_seq_id label_comp_id auth_asym_id "
             "auth_seq_id pdbx_PDB_ins_code pdbx_PDB_model_num Cartn_x Cartn_y Cartn_z occupancy").split()


def identifier(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip() and value not in ("?", ".")


def positive(value):
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) and int(value) > 0:
        return int(value)
    raise ValueError("expected positive integer")


@dataclass(frozen=True)
class Residue:
    model: int
    auth_asym_id: str
    auth_seq_id: str
    ins_code: str
    label_asym_id: str
    label_seq_id: int
    label_comp_id: str
    label_entity_id: str

    @property
    def auth(self):
        return self.model, self.auth_asym_id, self.auth_seq_id, self.ins_code

    @property
    def label(self):
        return self.model, self.label_asym_id, self.label_seq_id


class Crosswalk:
    def __init__(self):
        self.auth = defaultdict(list)
        self.label = defaultdict(list)
        self.sources = {}

    def observe(self, residue, row):
        if residue not in self.sources:
            self.auth[residue.auth].append(residue)
            self.label[residue.label].append(residue)
            self.sources[residue] = {"first_atom_site_row": row, "observed_atom_rows": 0}
        self.sources[residue]["observed_atom_rows"] += 1

    def resolve(self, claim):
        result = {"claim": claim, "status": "undeclared", "candidates": []}
        if not isinstance(claim, dict):
            return result
        try:
            model = positive(claim.get("model"))
            fields = set(claim) - {"model"}
            if fields == AUTH and all(identifier(claim[k]) for k in ("auth_asym_id", "auth_seq_id")):
                ins = claim["ins_code"]
                if ins != "" and not identifier(ins):
                    return result
                found = self.auth.get((model, claim["auth_asym_id"], claim["auth_seq_id"], ins), [])
            elif fields == LABEL and identifier(claim["label_asym_id"]):
                found = self.label.get((model, claim["label_asym_id"], positive(claim["label_seq_id"])), [])
            else:
                return result
        except ValueError:
            return result
        # A one-way hit is not enough if its counterpart names several residues.
        peers = found
        if len(found) == 1:
            residue = found[0]
            peers = dict.fromkeys((*self.auth[residue.auth], *self.label[residue.label]))
        result["candidates"] = [{**asdict(r), **self.sources[r]} for r in peers]
        result["status"] = "unique" if len(peers) == 1 else "ambiguous" if peers else "unknown"
        return result


MAX_EXPANDED_CIF_BYTES = 256 * 1024 * 1024


def read_crosswalk(data):
    index = Crosswalk()
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as archive:
                data = archive.read(MAX_EXPANDED_CIF_BYTES + 1)
        except (EOFError, OSError, zlib.error) as exc:
            raise AuditError("structure: invalid or incomplete gzip archive") from exc
        if len(data) > MAX_EXPANDED_CIF_BYTES:
            raise AuditError("structure: expanded mmCIF exceeds the size limit")
    try:
        document = gemmi.cif.read_string(data)
        if len(document) != 1:
            raise ValueError(f"expected exactly one data block, got {len(document)}")
        block = document.sole_block()
        entities = {}
        for raw_id, raw_type in block.find("_entity.", ["id", "type"]):
            entity, kind = map(gemmi.cif.as_string, (raw_id, raw_type))
            if not identifier(entity) or not identifier(kind) or entity in entities:
                raise ValueError("unknown or duplicate _entity declaration")
            entities[entity] = kind.lower()
        sites = block.find("_atom_site.", ATOM_TAGS)
        if not entities or not sites:
            raise ValueError("missing _entity or required _atom_site columns")
        for n, site in enumerate(sites, 1):
            entity, label, seq, comp, auth, author_seq, ins, model, *coords = map(gemmi.cif.as_string, site)
            if entity not in entities:
                raise ValueError(f"_atom_site row {n}: unknown entity {entity!r}")
            if entities[entity] != "polymer":
                continue
            # Gemmi handles CIF numbers with parenthesized standard uncertainties.
            xyz_occ = [gemmi.cif.as_number(s) for s in coords]
            if not all(map(math.isfinite, xyz_occ)) or xyz_occ[-1] <= 0:
                continue
            if not all(map(identifier, (label, comp, auth, author_seq))):
                raise ValueError(f"_atom_site row {n}: missing observed polymer identifiers")
            residue = Residue(positive(model), auth, author_seq, ins, label, positive(seq), comp, entity)
            index.observe(residue, n)
    except (ValueError, RuntimeError) as exc:
        raise AuditError(f"structure: {exc}") from exc
    return index
