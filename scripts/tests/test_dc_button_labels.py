"""_dc_button_rows / _dc_buttons 라벨 통합 테스트 — 방향 이모지 + 4열 배열 유지.

실행: python -m pytest scripts/tests/test_dc_button_labels.py  (또는 python scripts/tests/test_dc_button_labels.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import discord_card  # noqa: E402  (matplotlib 는 지연 import — import 만으로는 안전)
import send_kakao_digest as skd  # noqa: E402


def _slot(ko):
    for ko_, en, cat, key in discord_card._ASSETS:
        if ko_ == ko:
            return cat, key
    raise AssertionError(f"asset not found: {ko}")


def _digest_data():
    data = {}
    for ko, chg in (("코스피", 1.8), ("코스닥", -2.3), ("S&P500", 2.0),
                    ("나스닥", -0.04), ("구리", None)):
        cat, key = _slot(ko)
        data.setdefault(cat, {})[key] = {"change": chg}
    return data


def test_digest_row_labels_have_direction_emoji():
    rows = skd._dc_button_rows(_digest_data())
    flat = [lab for row in rows for lab, _ in row]
    assert "📈 코스피 +1.8%" in flat
    assert "⏬ 코스닥 -2.3%" in flat
    assert "⏫ S&P500 +2.0%" in flat
    assert "➖ 나스닥" in flat
    assert "➖ 구리" in flat


def test_digest_grid_is_4_columns_with_util_row():
    rows = skd._dc_button_rows(_digest_data())
    assert len(rows) >= 2
    for row in rows[:-1]:
        assert len(row) == 4
    assert rows[-1] == [("🌐 대시보드", skd.DASHBOARD_URL),
                        ("📊 시장 지표", skd.DASHBOARD_URL + "?p=market"),
                        ("🔄 지금 시세", "id:refresh_quotes")]


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: _dc_button_rows / _dc_buttons")