import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fetch_climate as fc

ONI_FIX = """ SEAS  YR   TOTAL   ANOM
  DJF 2026  26.13  -0.37
  JFM 2026  26.58  -0.14
  FMA 2026  27.30   0.13
  MAM 2026  28.06   0.48
"""

def test_parse_oni_last_row():
    assert fc.parse_oni(ONI_FIX) == {"value": 0.48, "season": "MAM", "year": 2026}

MTH_FIX = """ YR   MON  NINO1+2  ANOM   NINO3    ANOM   NINO4    ANOM   NINO3.4  ANOM
1950   1   23.01   -1.55   23.56   -2.10   26.94   -1.38   24.55   -1.99
2026   4   26.85    1.31   28.01    0.43   29.44    0.81   28.11    0.29
2026   5   26.23    1.81   28.30    1.05   29.98    1.07   28.75    0.82
"""

# 음수 SSTA 가 SST 에 붙는 고정폭 포맷(26.6-0.2) 포함
WK_FIX = """ Weekly SST data starts week centered on 2Sept1981

                Nino1+2      Nino3        Nino34        Nino4
 Week          SST SSTA     SST SSTA     SST SSTA     SST SSTA
 27JAN2021     24.6-0.4     25.7-0.2     25.9-0.7     27.1-1.1
 03JUN2026     26.3 2.6     28.4 1.5     29.0 1.3     30.0 1.1
 10JUN2026     26.1 2.7     28.3 1.6     29.2 1.5     30.1 1.3
"""

def test_parse_nino34_monthly_last_row():
    assert fc.parse_nino34_monthly(MTH_FIX) == {"value": 0.82, "year": 2026, "mon": 5}

def test_parse_nino34_weekly_last_row_and_prev():
    out = fc.parse_nino34_weekly(WK_FIX)
    assert out["value"] == 1.5
    assert out["weekEnding"] == "2026-06-10"
    assert out["prevValue"] == 1.3

def test_parse_nino34_weekly_handles_glued_negative():
    # 첫 데이터행(27JAN2021)만 주면 Nino34 SSTA = -0.7
    one = "\n".join(WK_FIX.splitlines()[:5])
    assert fc.parse_nino34_weekly(one)["value"] == -0.7

def test_derive_phase_thresholds():
    assert fc.derive_phase(0.48) == "neutral"
    assert fc.derive_phase(0.5) == "elnino"
    assert fc.derive_phase(-0.5) == "lanina"

def test_derive_strength_bands():
    assert fc.derive_strength(0.48) == "neutral"
    assert fc.derive_strength(0.8) == "weak"
    assert fc.derive_strength(1.2) == "moderate"
    assert fc.derive_strength(1.7) == "strong"
    assert fc.derive_strength(-2.1) == "very_strong"

def test_derive_trend():
    assert fc.derive_trend(1.3, 1.5) == "warming"
    assert fc.derive_trend(1.5, 1.3) == "cooling"
    assert fc.derive_trend(1.50, 1.52) == "steady"
    assert fc.derive_trend(None, 1.5) == "steady"

JMA_FIX = """# JMA NINO.3 SST anomaly (deg C)
2026 03 0.7
2026 04 0.8
2026 05 0.9
"""

def test_parse_jma_nino3_ok():
    assert fc.parse_jma_nino3(JMA_FIX) == {"value": 0.9, "asOf": "2026-05"}

def test_parse_jma_nino3_garbage_returns_none():
    assert fc.parse_jma_nino3("<html>unexpected</html>") is None
    assert fc.parse_jma_nino3("") is None
