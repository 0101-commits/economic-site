"""_krx_name 회귀 테스트 — pykrx 이름 조회가 Series 를 돌려줘도 JSON 이 깨지지 않아야 한다.

배경: 2026-08-06 KRX 응답 저하 시 pykrx 의 `df.loc[ticker, "종목명"]` 이 중복 인덱스 때문에
pandas Series 를 반환 → ETF movers 리스트에 실려 `json.dump(data)` 가
`TypeError: Object of type Series is not JSON serializable` 로 죽고 수집 전체가 유실됐다.

실행: python -m pytest scripts/tests/test_krx_name.py  (또는 python scripts/tests/test_krx_name.py)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fetch_data import _krx_name  # noqa: E402


class FakeSeries:
    """pandas Series 대역 — .iloc / len 만 흉내낸다(테스트에 pandas 의존 금지)."""

    def __init__(self, values):
        self._v = list(values)

    def __len__(self):
        return len(self._v)

    @property
    def iloc(self):
        return self._v

    def __str__(self):
        return "ticker\n069500  KODEX 200\nName: 종목명, dtype: object"


def _boom(_t):
    raise RuntimeError("KRX 502")


def test_scalar_name_passthrough():
    assert _krx_name(lambda t: "KODEX 200", "069500") == "KODEX 200"


def test_duplicate_index_series_takes_first():
    assert _krx_name(lambda t: FakeSeries(["KODEX 200", "KODEX 200"]), "069500") == "KODEX 200"


def test_empty_series_falls_back_to_ticker():
    assert _krx_name(lambda t: FakeSeries([]), "069500") == "069500"


def test_lookup_exception_falls_back_to_ticker():
    assert _krx_name(_boom, "069500") == "069500"


def test_blank_and_none_fall_back_to_ticker():
    assert _krx_name(lambda t: "   ", "069500") == "069500"
    assert _krx_name(lambda t: None, "069500") == "069500"


def test_result_is_always_json_serializable():
    for fn in (lambda t: FakeSeries(["A", "B"]), _boom, lambda t: None):
        json.dumps({"name": _krx_name(fn, "069500")}, ensure_ascii=False)


if __name__ == "__main__":
    for _n, _f in sorted(globals().items()):
        if _n.startswith("test_"):
            _f()
            print(f"ok {_n}")
    print("OK: _krx_name")
