# ENSO 기후·거시 카드 시각화 재설계 — 설계 문서

날짜: 2026-06-23
대상: `index.html` `#ensoCard` (market 페이지) + `scripts/fetch_climate.py`

## 문제
현재 `#ensoCard`는 텍스트·칩 나열 위주(실측 한 줄 배너 + 로직 도식 + 원자재/섹터 텍스트 리스트 + 시간축 거시 텍스트 카드 + 접힌 예측 이미지). "어떤 자산에 영향 주는지"가 눈에 안 들어옴. 차트 0개.

## 목표
1. **실측 기온 추이 차트** — ONI 시계열을 네이티브 차트로.
2. **예측 그래프 시각화** — 공식 예측 차트를 추이 옆에 prominent 패널로.
3. **경제 영향 시각화** — 원자재/섹터/거시 영향을 텍스트→시각 신호로.

## 정직성 제약 (불변)
- 모든 수치는 실측(NOAA). 영향 방향은 IMF WP/15/89 + 기후학 전형패턴(예보 아님). 기존 면책/출처 유지.
- 데이터 없으면 "갱신 대기" 안내, 절대 날조 금지(기존 패턴 그대로).
- 단일 `index.html` 인라인, Chart.js, 빌드 없음. CSP 준수(eval/외부 CDN 추가 금지).

## 예측 데이터 — 결정 (deviation 기록)
사용자는 "공식 확률예측 네이티브 차트"를 선택했으나, 구현 전 검증 결과 **공개된 신뢰 가능한 수치 ENSO 확률예측 엔드포인트가 없음**(CPC RONI·IRI·BOM·CFSv2 모두 이미지 중심 또는 404). 정직성 원칙상 가짜 예측값 생성 불가, 취약한 HTML 스크래핑은 dead-code/파손 위험.
→ **예측 = 공식 예측 차트-이미지**(NOAA CPC ENSO 확률 PNG + NOAA CFSv2 Niño3.4 plume GIF)를 접힘 해제하여 추이 차트 옆 패널로 승격. 이미지 로드 실패 시 기존 onerror→링크 폴백 유지. 수치 네이티브 예측 차트는 신뢰 가능한 공개 수치 출처 확보 시로 보류.

## 데이터 변경 (`scripts/fetch_climate.py`)
- 신규 `parse_oni_history(text)`: `oni.ascii.txt` 전체 행 파싱 → 최근 120개월 `[{"t":"YYYY-MM","v":anom}]`. 시즌→대표월 매핑(DJF→01 … NDJ→12).
- `fetch_enso()`에 독립 try/except로 `enso["oni_history"]` 추가 + `stale["oni_history"]` 플래그. 실패해도 다른 소스 보존(기존 패턴).
- `fetch_data.py`/`validate_data.py` 수정 불필요: 전자는 `fetch_enso()` 결과를 통째 저장(일일 런), 후자의 climate 체크는 비차단 경고.
- 예측 fetch 추가 안 함(위 결정).

## 프론트 구조 (`#ensoCard` 본문, 위→아래)
1. **헤드라인 스트립**: 현재 ONI 큰 숫자 + 국면 배지 + 추세 화살표 + 한 줄 평이 요약(기존 실측 배너 확장).
2. **기온 추이 & 예측**
   - 상단: 실측 ONI 라인(최근 ~10년) — Chart.js. 엘니뇨(>+0.5°C 빨강)/라니냐(<−0.5°C 파랑) 음영 + 0/±0.5 기준선 + "현재" 마커. `oni_history` 없으면 최신 1점 + "추이 수집 대기" 안내(날조 금지).
   - 하단: 공식 예측 차트-이미지 패널(NOAA CPC 확률 + CFSv2 plume), 기본 표시.
3. **경제 영향** — 렌즈 탭 2개 유지, 본문만 시각화:
   - 원자재·섹터 탭 → **방향성 바**(상승▲빨강/하락▼파랑, 길이=변동성 高/中/低) + 수혜🔵/부담🔴 종목칩 2열. CSS 기반(캔버스 X).
   - 시간축 거시 탭 → **히트맵**(행=자산, 열=단/중/장기, 색=위험🔴/기회🔵/혼조🟠), 칸 호버=근거. CSS grid.
4. 🔗 분석 로직 흐름 + 출처/면책 — 유지·간소화.

## 단위 경계
- `fetch_climate.parse_oni_history` — 입력 텍스트→시계열, 순수함수, 단독 테스트 가능.
- 프론트 렌더 함수: `ensoTrendChartHTML`+`buildEnsoTrendChart`(차트), `ensoForecastPanelHTML`(이미지 패널), `ensoSectorHTML`(방향성 바), `ensoMacroHTML`(히트맵). 각자 데이터 부재 시 안전 폴백.

## 검증
- `python scripts/fetch_climate.py`류 standalone로 `oni_history` shape 확인(커밋 금지 — data.json은 봇 소유).
- `python scripts/validate_data.py`로 게이트 통과 확인.
- 로컬 `python -m http.server`로 카드 렌더/차트/탭/폴백 육안 확인.

## 미적용 (YAGNI)
- 수치 네이티브 예측 차트(출처 부재).
- 주간 Niño3.4 시계열 차트(월별 ONI로 충분).
- 새 데이터 소스/파이프라인 워크플로 변경.
