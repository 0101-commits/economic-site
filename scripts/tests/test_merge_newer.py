import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import merge_newer as m

OLD = "2026-09-30T10:08:00+09:00"
NEW = "2026-09-30T10:26:00+09:00"


def base(ts, kospi, extra=None):
    d = {"lastUpdated": ts, "indices": {"KOSPI": {"price": kospi, "change": 0.1}},
         "fx": {}, "commodities": {},
         "history": {"indices": {"KOSPI": [{"date": "2026-09-29", "close": 1.0},
                                           {"date": "2026-09-30", "close": kospi}]}}}
    d.update(extra or {})
    return d


def run(tmp_path, r, o, raw_origin=None):
    rp, op, out = (tmp_path / n for n in ("r.json", "o.json", "out.json"))
    rp.write_text(json.dumps(r), encoding="utf-8")
    op.write_text(raw_origin if raw_origin is not None else json.dumps(o), encoding="utf-8")
    m.main(str(rp), str(op), str(out))
    return json.loads(out.read_text(encoding="utf-8"))


def test_origin_newer_wins(tmp_path):
    r = run(tmp_path, base(OLD, 100), base(NEW, 200))
    assert r["indices"]["KOSPI"]["price"] == 200
    assert r["history"]["indices"]["KOSPI"][-1]["close"] == 200
    assert r["lastUpdated"] == NEW
    meta = json.loads((tmp_path / "data_meta.json").read_text())
    assert meta["lastUpdated"] == NEW


def test_run_newer_wins(tmp_path):
    r = run(tmp_path, base(NEW, 100), base(OLD, 200))
    assert r["indices"]["KOSPI"]["price"] == 100 and r["lastUpdated"] == NEW


def test_missing_symbol_keeps_run(tmp_path):
    o = base(NEW, 200)
    o["indices"] = {}
    r = run(tmp_path, base(OLD, 100), o)
    assert r["indices"]["KOSPI"]["price"] == 100


def test_malformed_origin_unchanged(tmp_path):
    src = base(OLD, 100)
    r = run(tmp_path, src, None, raw_origin="{<<<<")
    assert r == src


def test_snapshot_block_newer_wins(tmp_path):
    r = run(tmp_path, base(NEW, 1, {"stockFlows": {"generatedAt": OLD, "items": [1]}}),
            base(OLD, 1, {"stockFlows": {"generatedAt": NEW, "items": [2]}}))
    assert r["stockFlows"]["items"] == [2]
