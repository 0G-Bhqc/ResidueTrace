import json
from collections import Counter
from pathlib import Path
from runpy import run_path

import pytest
from residuetrace import audit

bench = run_path(str(Path(__file__).with_name("evaluate.py")))


def test_reference_scores_and_pairs(tmp_path):
    root = tmp_path / "dataset"
    bench["prepare"](root)
    items, gold = (bench["read_json"](root / name) for name in ("index.json", "gold.json"))
    assert {i["entry"] for i in items if i["split"] == "dev"}.isdisjoint(
        i["entry"] for i in items if i["split"] == "test")
    for split, n_literal in (("dev", 6), ("test", 4)):
        subset = [i for i in items if i["split"] == split]
        assert Counter(gold[i["id"]] for i in subset) == {k: 2 for k in bench["LABELS"]}
        for predictor, expect in (("mapped", 6), ("literal", n_literal)):
            preds = {i["id"]: bench[predictor](root / i["manifest"]) for i in subset}
            assert bench["score"](subset, gold, preds)["correct"] == expect
        matched = {}
        for i in subset:
            path = root / i["manifest"]
            m = bench["read_json"](path)
            assert audit(path)["ok"] is (gold[i["id"]] == "consistent")
            region, = m["regions"]
            if gold[i["id"]] != "insufficient":
                key = (m["structure"]["sha256"], m["figure"]["sha256"], json.dumps(region, sort_keys=True))
                matched.setdefault(key, {})[gold[i["id"]]] = m["table"]["sha256"]
        assert len(matched) == 2
        for pair in matched.values():
            assert pair["consistent"] != pair["conflict"]


@pytest.mark.parametrize("preds", [{}, {"case": "unsupported"}, {"case": "conflict", "extra": "conflict"}])
def test_scores_never_drop_bad_predictions(preds):
    with pytest.raises(ValueError):
        bench["score"]([{"id": "case"}], {"case": "conflict"}, preds)


def test_duplicate_prediction_rejected(tmp_path):
    path = tmp_path / "p.json"
    path.write_text('{"case":"consistent", "case":"conflict"}')
    with pytest.raises(ValueError, match="Duplicate"):
        bench["predictions_file"](path)
