#!/usr/bin/env python3
"""기후(ENSO) → 경제 영향 매핑 — data.json.climate.impact 생성.

왜: fetch_climate.py 가 만든 실측 ENSO 국면(data.json.climate.enso)을, IMF 논문
    "Fair Weather or Foul? The Macroeconomic Effects of El Niño"
    (Cashin · Mohaddes · Raissi, IMF Working Paper WP/15/89, 2015)의 거시 결론에
    매핑하여 단기(0~6M)·중기(6~12M)·장기(1~3Y) 3단계 파급을 구조화한다.
    프론트(index.html)의 '🌊 시간축 거시 파급' 탭이 이 블록을 읽어 렌더한다.

정직성 원칙(이 파일의 가장 중요한 규칙):
  - 국면(phase)·강도(strength)·ONI 값은 전부 실측(NOAA)에서 온다 — 여기서 날조하지 않는다.
  - 영향의 '방향/자산군'은 논문·기후학에 근거한 *전형 패턴*이며 실시간 예보·매매 신호가 아니다.
  - IMF 논문은 '엘니뇨'를 직접 분석한다. '라니냐'는 논문에 대칭 분석이 없으므로 일반 ENSO
    기후학 + 원자재 수급 로직 기반 '거울상 추정'으로 표기한다(confidence='estimated').
  - 매핑에 없는 국면이면 빈 구조 대신 'neutral'로 폴백하되, 값을 지어내지 않는다.

의존성: 표준 라이브러리(json/os/sys)만 사용 — GitHub Actions 에 새 pip 설치가 필요 없다.

사용:
  - 파이프라인: fetch_data.py 가 `import climate_impact` 후 build_impact(enso) 호출.
  - 단독 실행: `python scripts/climate_impact.py [data.json경로]`
      → 기존 data.json 의 climate.enso 를 읽어 climate.impact 를 병합 저장.
"""
import json
import os
import sys

# ── stance 상수 — 프론트 색상 키와 1:1 대응(절대 문자열 변경 금지) ───────────────
RISK = "risk"                # 🔴 위험 (해당 자산군에 부담/하방)
OPPORTUNITY = "opportunity"  # 🔵 기회 (해당 자산군에 수혜/상방)
MIXED = "mixed"              # ⚪ 혼조 (방향 불확실 — 산지·정책·환율에 좌우)

# IMF 논문 출처 — 카드 하단 인용에 그대로 노출된다.
SOURCE = {
    "title": "Fair Weather or Foul? The Macroeconomic Effects of El Niño",
    "authors": "Cashin, Mohaddes & Raissi",
    "ref": "IMF Working Paper WP/15/89 (2015)",
    "url": "https://www.imf.org/external/pubs/ft/wp/2015/wp1589.pdf",
}
DISCLAIMER = ("과거 ENSO 사이클의 전형적 방향이며 실시간 예보·매매 신호가 아닙니다. "
              "실제 가격은 재고·달러·OPEC+·지정학 등 복합 요인에 좌우됩니다 — 투자 참고용.")


def _asset(name, stance, note):
    """자산군 1건 — name(표시명), stance(risk/opportunity/mixed), note(근거 한 줄)."""
    return {"name": name, "stance": stance, "note": note}


def _horizon(key, label, timeframe, icon, mechanism, assets):
    """시간대 1건 — key(short/mid/long), label(단기 등), timeframe(0~6개월 등)."""
    return {"key": key, "label": label, "timeframe": timeframe,
            "icon": icon, "mechanism": mechanism, "assets": assets}


# ── 국면별 × 시간대별 경제 영향 매핑 ─────────────────────────────────────────────
# confidence: 'imf'(논문 직접 분석) / 'estimated'(기후학 기반 거울상 추정) / 'low_signal'(신호 약함)
IMPACT_MAP = {
    # 🔴 엘니뇨 — IMF 논문 직접 분석 대상
    "elnino": {
        "confidence": "imf",
        "short": _horizon(
            "short", "단기", "0~6개월", "⏱️",
            "동남아·인도·호주 가뭄·고온 → 열대 농산물 감산·가격 변동성↑",
            [
                _asset("설탕·커피·코코아·팜유", OPPORTUNITY,
                       "감산 → 가격↑; 비료·농산물생산(KG케미칼·남해화학) 수혜"),
                _asset("식품가공 (CJ제일제당·대상·롯데웰푸드)", RISK,
                       "설탕·커피·팜유 원재료비↑ → 마진 압박"),
                _asset("곡물 (밀·옥수수·대두)", MIXED,
                       "미 중서부 양호 vs 호주·동남아 건조 → 혼조"),
            ]),
        "mid": _horizon(
            "mid", "중기", "6~12개월", "🔄",
            "북반구 겨울 온난 → 난방 수요 둔화 + 인니 강우로 광물 물류 차질",
            [
                _asset("천연가스 (한국가스공사)", RISK,
                       "온난한 겨울 → 난방·LNG 수요 둔화"),
                _asset("니켈·주석", MIXED,
                       "인도네시아 강우·물류 차질 가능 → 공급 변동성"),
                _asset("정유·정제마진", MIXED,
                       "IMF: 에너지가 상방 압력 vs 난방 수요 둔화 → 방향 혼재"),
            ]),
        "long": _horizon(
            "long", "장기", "1~3년", "🌐",
            "IMF: 에너지·비연료 원자재가↑ → 글로벌 CPI↑, GDP 영향은 국가별 차등",
            [
                _asset("인플레 수혜 (원자재·에너지·소재)", OPPORTUNITY,
                       "원자재가 상승 국면에서 상대 수혜"),
                _asset("금리민감 성장주·장기채", RISK,
                       "인플레↑ → 금리 부담 확대"),
                _asset("농업·수입의존 신흥국 (인도·인니·호주)", RISK,
                       "IMF: 해당국 단기 성장 둔화(가뭄·작황)"),
                _asset("미국·유럽 경기", OPPORTUNITY,
                       "IMF: 일부 선진국은 단기 성장 소폭 플러스(이례적 결과)"),
            ]),
    },
    # 🔵 라니냐 — 논문은 엘니뇨 중심. 기후학 기반 '거울상 추정'.
    "lanina": {
        "confidence": "estimated",
        "short": _horizon(
            "short", "단기", "0~6개월", "⏱️",
            "남미(아르헨·브라질 남부) 가뭄 + 동남아 과우 → 곡물 변동성↑",
            [
                _asset("대두·옥수수", OPPORTUNITY,
                       "남미 가뭄 감산 → 가격↑; 비료·곡물생산 수혜"),
                _asset("사료·축산 (한일사료·팜스코)·식품가공", RISK,
                       "곡물 원가↑ → 마진 압박"),
                _asset("커피", MIXED,
                       "산지별 강우 편차로 방향 혼조"),
            ]),
        "mid": _horizon(
            "mid", "중기", "6~12개월", "🔄",
            "북반구 한파 → 난방 수요↑ + 페루·칠레 폭우로 구리 조업 차질",
            [
                _asset("원유·천연가스 (S-Oil·GS·한국가스공사)", OPPORTUNITY,
                       "북반구 한파 → 난방·정제 수요↑"),
                _asset("구리·비철 (풍산·LS·고려아연)", OPPORTUNITY,
                       "남미 폭우 → 광산·물류 차질 → 가격↑·스프레드 개선"),
                _asset("구리 소비 전방 (전선·건설 원가)", RISK,
                       "구리가 상승 → 원가 부담"),
            ]),
        "long": _horizon(
            "long", "장기", "1~3년", "🌐",
            "에너지·금속발 인플레 압력 + GDP는 지역 편차(논문 근거 약함 — 신중)",
            [
                _asset("에너지·금속 인플레 수혜", OPPORTUNITY,
                       "원자재 상승 국면 상대 수혜"),
                _asset("곡물·에너지 수입의존 경제", RISK,
                       "수입 물가 부담 확대"),
                _asset("거시 GDP 영향", MIXED,
                       "라니냐는 지역별 편차가 커 단정 곤란 — 거울상 추정"),
            ]),
    },
    # ⚪ 중립 — ENSO 신호 약함. 펀더멘털 우세.
    "neutral": {
        "confidence": "low_signal",
        "short": _horizon(
            "short", "단기", "0~6개월", "⏱️",
            "ENSO 공급 충격 제한 → 계절성·환율 영향이 우세",
            [
                _asset("농산물 전반", MIXED,
                       "평년 작황 가정 → 기후 프리미엄 약함"),
            ]),
        "mid": _horizon(
            "mid", "중기", "6~12개월", "🔄",
            "에너지·금속은 재고·OPEC+·중국 수요가 가격을 주도",
            [
                _asset("원유·금속", MIXED,
                       "ENSO보다 펀더멘털·달러지수(DXY) 변수 우세"),
            ]),
        "long": _horizon(
            "long", "장기", "1~3년", "🌐",
            "ENSO발 거시 전이 신호가 약한 국면",
            [
                _asset("시장 전반", MIXED,
                       "특정 섹터 일방 베팅보다 환율·금리 흐름 연동 주목"),
            ]),
    },
}

HORIZON_ORDER = ["short", "mid", "long"]


def _intensity(oni_value):
    """ONI 절댓값 → 0~1 게이지 값.

    |ONI|=2.0(매우 강함)에서 1.0 으로 포화. 게이지 폭(%)에 그대로 쓰인다.
    값이 숫자가 아니면(미수집) 0.0 — 게이지가 비어 보이게 한다(날조 금지).
    """
    try:
        return round(max(0.0, min(abs(float(oni_value)) / 2.0, 1.0)), 3)
    except (TypeError, ValueError):
        return 0.0


def build_impact(enso):
    """실측 enso 블록 → climate.impact 블록 생성.

    enso(dict): fetch_climate.fetch_enso() 산출물. phase/strength/oni 를 읽는다.
    반환(dict): activePhase·activeStrength·intensity(0~1)·oni·asOf·source·disclaimer·
                horizons(순서)·map(전 국면 매핑). 프론트는 map[선택국면][시간대] 로 렌더.
    enso 가 비정상이면 'neutral'로 폴백(빈 화면 대신 안전한 기본값) — 값은 지어내지 않음.
    """
    enso = enso if isinstance(enso, dict) else {}
    phase = enso.get("phase") or "neutral"
    if phase not in IMPACT_MAP:
        phase = "neutral"
    oni = enso.get("oni") if isinstance(enso.get("oni"), dict) else {}
    oni_value = oni.get("value")
    return {
        "activePhase": phase,
        "activeStrength": enso.get("strength") or "neutral",
        "intensity": _intensity(oni_value),
        "oni": (oni_value if isinstance(oni_value, (int, float)) else None),
        "asOf": oni.get("asOf") or "",
        "source": SOURCE,
        "disclaimer": DISCLAIMER,
        "horizons": HORIZON_ORDER,
        "map": IMPACT_MAP,
    }


def merge_into_data_json(path="data.json"):
    """단독 실행용 — 기존 data.json 의 climate.enso 를 읽어 climate.impact 를 병합 저장.

    fetch_climate 가 한 번도 돌지 않아 climate.enso 가 없으면 아무것도 쓰지 않고 False.
    (값 날조 금지 — enso 가 있어야 국면이 정해진다.)
    """
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        print(f"[climate_impact] {path} 로드 실패: {e}")
        return False
    climate = d.get("climate")
    if not isinstance(climate, dict) or not isinstance(climate.get("enso"), dict):
        print("[climate_impact] climate.enso 없음 — 먼저 fetch_climate 실행 필요. 건너뜀.")
        return False
    climate["impact"] = build_impact(climate["enso"])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    imp = climate["impact"]
    print(f"[climate_impact] impact 병합 완료: activePhase={imp['activePhase']}, "
          f"intensity={imp['intensity']}, asOf={imp['asOf']!r}")
    return True


if __name__ == "__main__":
    # Windows 콘솔(cp949)에서 한글·em-dash print 가 깨져 죽는 것 방지(CI Linux 는 영향 없음).
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    target = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    ok = merge_into_data_json(target)
    sys.exit(0 if ok else 1)
