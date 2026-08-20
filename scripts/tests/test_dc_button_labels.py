"""_dc_select / _dc_buttons 통합 테스트 — v4 버튼 다이어트(기획 ed0e5496) 가드.

계약: 다이제스트 컴포넌트 = 유틸 버튼 1행 3개 + 지표 드롭다운 ≤25옵션.
드롭다운 값은 전부 NAVER_LINKS 키(Worker goto_link 가 URL 로 해석), 라벨은
방향 이모지 스냅샷. 구 16버튼 그리드(_dc_button_rows)는 존재 자체가 회귀.

실행: python -m pytest scripts/tests/test_dc_button_labels.py  (또는 python scripts/tests/test_dc_button_labels.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import discord_card  # noqa: E402  (matplotlib 는 지연 import — import 만으로는 안전)
import notify_discord  # noqa: E402
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


def test_select_labels_have_direction_emoji():
    opts = skd._dc_select(_digest_data())
    labels = [lab for lab, _ in opts]
    assert "📈 코스피 +1.8%" in labels
    assert "⏬ 코스닥 -2.3%" in labels
    assert "⏫ S&P500 +2.0%" in labels
    assert "➖ 나스닥" in labels


def test_select_values_all_resolvable():
    opts = skd._dc_select(_digest_data())
    assert 0 < len(opts) <= 25
    for _, key in opts:
        assert key in notify_discord.NAVER_LINKS, f"드롭다운 값이 NAVER_LINKS 에 없음: {key}"


def test_util_buttons_single_row_of_three():
    row = skd._dc_buttons()
    assert row == [("🌐 대시보드", skd.DASHBOARD_URL),
                   ("📊 시장 지표", skd.DASHBOARD_URL + "?p=market"),
                   ("🔄 지금 시세", "id:refresh_quotes")]


def test_v3_button_grid_removed():
    assert not hasattr(skd, "_dc_button_rows"), "구 16버튼 그리드가 되살아남 — v4 회귀"


def test_select_component_shape():
    comp = notify_discord._select_component([("📈 코스피 +1.8%", "KOSPI")])
    assert comp["type"] == 1
    inner = comp["components"][0]
    assert inner["type"] == 3 and inner["custom_id"] == "goto_link"
    assert inner["options"] == [{"label": "📈 코스피 +1.8%", "value": "KOSPI"}]
    assert notify_discord._select_component(None) is None
    assert notify_discord._select_component([]) is None


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: _dc_select / _dc_buttons / _select_component")
