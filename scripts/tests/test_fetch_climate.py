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
