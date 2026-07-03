import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import send_kakao_digest as skd

# MOF 국채금리 CSV 실물 형식 (Shift-JIS 디코딩 후) — 헤더 2줄 + 데이터 + 꼬리 빈행/주석
JGB_FIX = """国債金利情報 (令和8年7月),,,,,,,,,,,,,,,(単位 : %)
基準日,1年,2年,3年,4年,5年,6年,7年,8年,9年,10年,15年,20年,25年,30年,40年
R8.7.1,1.164,1.4,1.554,1.777,1.959,2.099,2.255,2.421,2.572,2.711,3.286,3.632,3.889,3.883,3.782
R8.7.2,1.166,1.395,1.567,1.797,1.979,2.137,2.3,2.47,2.627,2.778,3.359,3.711,3.956,3.937,3.826
,,,,,,,,,,,,,,,
利回りはcsvファイルで提供しています,,,,,,,,,,,,,,,
"""


def test_parse_mof_era_date_reiwa():
    assert skd._parse_mof_era_date("R8.7.2").strftime("%Y-%m-%d") == "2026-07-02"


def test_parse_mof_era_date_heisei():
    assert skd._parse_mof_era_date("H31.4.30").strftime("%Y-%m-%d") == "2019-04-30"


def test_parse_mof_era_date_rejects_header():
    assert skd._parse_mof_era_date("基準日") is None


def test_parse_jgb_10y_extracts_10y_column():
    assert skd.parse_jgb_10y(JGB_FIX) == {"2026-07-01": 2.711, "2026-07-02": 2.778}


def test_parse_jgb_10y_skips_dash_value():
    row = "R8.7.3,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,1.9,-,3.3,3.7,3.9,3.9,3.8\n"
    assert skd.parse_jgb_10y(row) == {}
