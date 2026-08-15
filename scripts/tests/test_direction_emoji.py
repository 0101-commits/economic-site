"""direction_emoji / dir_label 회귀 테스트 — 디스코드 버튼 라벨 방향 이모지.

실행: python -m pytest scripts/tests/test_direction_emoji.py  (또는 python scripts/tests/test_direction_emoji.py)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from notify_discord import direction_emoji, dir_label  # noqa: E402


def test_flat_and_missing():
    assert direction_emoji(None) == "➖"
    assert direction_emoji(0.0) == "➖"
    assert direction_emoji(0.049) == "➖"
    assert direction_emoji(-0.049) == "➖"


def test_normal_direction():
    assert direction_emoji(0.05) == "📈"
    assert direction_emoji(1.9) == "📈"
    assert direction_emoji(-0.05) == "📉"
    assert direction_emoji(-1.9) == "📉"


def test_intensity_threshold_e2():
    assert direction_emoji(2.0) == "⏫"
    assert direction_emoji(3.5) == "⏫"
    assert direction_emoji(-2.0) == "⏬"
    assert direction_emoji(-3.5) == "⏬"


def test_non_numeric_falls_back_flat():
    assert direction_emoji("1.8") == "📈"
    assert direction_emoji("abc") == "➖"


def test_nan_is_flat():
    assert direction_emoji(float("nan")) == "➖"


def test_dir_label_accepts_numeric_string():
    assert dir_label("코스피", "1.8") == "📈 코스피 +1.8%"


def test_dir_label_non_numeric_string_is_flat():
    assert dir_label("구리", "abc") == "➖ 구리"


def test_dir_label_has_emoji_name_pct():
    assert dir_label("코스피", 1.8) == "📈 코스피 +1.8%"
    assert dir_label("S&P500", 2.0) == "⏫ S&P500 +2.0%"
    assert dir_label("코스닥", -2.3) == "⏬ 코스닥 -2.3%"


def test_dir_label_omits_pct_when_flat():
    assert dir_label("구리", None) == "➖ 구리"
    assert dir_label("나스닥", -0.04) == "➖ 나스닥"
    assert dir_label("N 삼성전자", 0.8) == "📈 N 삼성전자 +0.8%"


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: direction_emoji / dir_label")