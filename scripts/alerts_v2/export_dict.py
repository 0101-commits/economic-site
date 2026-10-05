"""사전 → 화면용 JSON(app/src/lib/alerts/dict.json). 화면은 이 파일만 읽고, 파리티 검사가 둘을 맞춘다."""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from alerts_v2 import FAMILIES, LEVELS, PACKAGES, STRENGTHS, SIGMA  # noqa: E402
from alerts_v2 import schema  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "app", "src", "lib", "alerts", "dict.json")
FAMILY_KO = {"A": "급변", "B": "기록 · 마디", "C": "임계 · 단계", "D": "수급", "E": "일정 · 발표",
             "F": "공시 · 종목", "G": "렌즈 · 메르", "H": "실물 · 월간"}
LEVEL_KO = {"alarm": "경보", "alert": "알림", "notice": "안내", "record": "기록"}
PACKAGE_KO = {"quiet": "조용히", "normal": "보통", "many": "많이"}
STRENGTH_KO = {"normal": "보통", "big": "크게", "huge": "아주 크게", "value": "값 직접"}


def build() -> dict:
    events = schema.load_events()
    rows = []
    for ev in events:
        rows.append({
            "id": ev["id"], "name": ev["name"], "family": ev["family"], "level": ev["level"],
            "targets": ev["targets"], "defaultOn": ev.get("default_on", []), "run": ev["run"],
            "enabled": ev.get("enabled", True), "cooldown": ev.get("cooldown"),
            "strength": ev["judge"] == "swing_sigma",      # 세기 3단을 고를 수 있는 사건
            "userValue": ev["id"].startswith("U"),
        })
    return {
        "version": 2,
        "families": [{"id": f, "name": FAMILY_KO[f]} for f in FAMILIES],
        "levels": [{"id": l, "name": LEVEL_KO[l]} for l in LEVELS],
        "packages": [{"id": p, "name": PACKAGE_KO[p]} for p in PACKAGES],
        "strengths": [{"id": s, "name": STRENGTH_KO[s], "sigma": SIGMA.get(s)} for s in STRENGTHS],
        "events": rows,
    }


def main(out: str = OUT) -> str:
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(build(), f, ensure_ascii=False, indent=1)
        f.write("\n")
    return out


if __name__ == "__main__":
    print(main())
