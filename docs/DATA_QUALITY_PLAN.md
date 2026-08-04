# 데이터 정합성·실시간성·최신성 고도화 기획안

작성 2026-08-04 · 대상 `economic-site` (GitHub Pages + Actions + Cloudflare Worker)

---

## 0. 한 줄 요약

> **파이프라인은 살아 있는데 게이트가 실패를 통과시킨다.**
> 개별 소스가 죽어도 `fetch_data.py`가 직전 값을 보존하고, `validate_data.py`는 골격만 검사하므로,
> 몇 년 전에 멈춘 지표가 화면에서는 오늘 값처럼 보인다.
> 해결책은 소스를 하나씩 땜질하는 게 아니라 **모든 지표에 as-of 계약과 신선도 SLA를 부여하고,
> 그 계약을 게이트·UI·알림 세 곳이 같은 표 하나로 공유**하게 만드는 것이다.

---

## 1. 진단 (전부 실측, 2026-08-04)

### 1.1 값이 틀린 데이터 — 정합성

| # | 항목 | 증상 | 근거 |
|---|---|---|---|
| **D1** | `sentiment.vkospi` | 값 **78.3**. 같은 시점 VIX 15.99, KOSPI 6,222(사상 최고권). 3개월째 68~82 유지 = 변동성지수로 성립 불가 | git 700커밋 역추적 |
| **D2** | `economicCalendar` | 미국 PPI가 07‑21·08‑03 두 날짜에 **동일 act(-0.3%)/fore(+0.6%)** 복제. 지표명 단위로 값을 붙여 날짜별 실적이 뭉개짐 | `data.json` |
| **D3** | `yieldCurve.kr` | `series` 라벨 5개(`1Y,5Y,10Y,20Y,30Y`) vs `current` 값 10개. 화면은 전역 상수 `yieldCurveTerms`(10종)를 써서 무사하나 **데이터 계약 위반** — 이 필드를 믿는 소비자는 전부 오배열 | `index.html:8687` |
| **D4** | `realestate.kr` 단위 의심 | `unsold_kr` = 296,502호(한국 미분양 실제 수준 6~7만호), `start_kr` "착공 실적"인데 값 102.17(지수형). `prev` 필드가 소수점 12자리(294207.611579255) = **실제 직전값이 아니라 chg로 역산한 파생값** | `data.json` |
| **D5** | VKOSPI 범위 가드 무력 | `_is_valid_vkospi`가 `5 < v < 100`. 과거에 유가 86.55가 이 가드를 통과해 카톡으로 "VKOSPI 86.5"가 나간 전례가 **코드 주석에 기록돼 있음**. 지금도 같은 폭이라 재발 | `fetch_data.py:3981` |

### 1.2 최신성 결손 — 죽었는데 살아 보이는 것

| # | 항목 | 마지막 실측 | 원인 |
|---|---|---|---|
| **S1** | `stockMovers` | as_of **2026‑07‑29** (6일 전) | `diagnostics.stockMoversSource="FAILED"` 상시. `_KRX_LOGIN_AVAILABLE=False` → **`KRX_ID`/`KRX_PW` 시크릿 미설정** → pykrx가 KRX 로그인 실패 (`fetch_data.py:244`) |
| **S2** | `sentiment.vkospi` | as_of **2026‑07‑27** (8일 전) | 폴백 4단계가 **전부 사망** (§1.3 표) |
| **S3** | 일본 CPI | **2021‑06** | FRED `JPNCPIALLMINMEI` 단종 |
| **S4** | 영국 실질GDP | **2020‑07** | FRED `CLVMNACSCAB1GQUK` 단종 |
| **S5** | 유로존 실업률 | **2023‑01** | FRED `LRHUTTTTEZM156S` 단종 |
| **S6** | 일본 광공업생산 | **2024‑03** | FRED `JPNPROINDMISMEI` 단종 |
| **S7** | 중국 CPI | **2025‑04** | FRED `CHNCPIALLMINMEI` 단종 |
| **S8** | 독일·영국 CPI | **2025‑03** | FRED `DEUCPIALLMINMEI` / `GBRCPIALLMINMEI` 단종 |
| **S9** | `news` 16토픽 중 **6개 상시 공백** | — | 채권·원자재·원유·비철금속·미국CPI·영국경기 |
| **S10** | PMI 7종 + 한국 KeyStat 4종 | history **1포인트** | 추세 차트 렌더 불가 |

> S3~S8은 **수집 버그가 아니다.** `fredgraph.csv`로 FRED 원본을 직접 조회해 확인한 결과,
> FRED가 OECD MEI 계열 전체를 폐기해 원본 시리즈 자체가 그 날짜에서 끝나 있다.
> `fetch_data.py`는 정직하게 마지막 값을 가져왔을 뿐이다. **소스 교체 외에 방법이 없다.**

### 1.3 VKOSPI 폴백 4단계 전멸 (실측)

| 순위 | 소스 | 실측 결과 |
|---|---|---|
| 1 | KRX OpenAPI `/idx/kospi_dd_trd` 에서 이름에 "변동성" 검색 | VKOSPI는 코스피 지수 계열이 아니라 **파생상품지수** 계열 → 이 엔드포인트에 애초에 없음 (`fetch_data.py:4166`) |
| 2 | `finance.naver.com/sise/sise_index.naver?code=KSVKOSPI` | HTTP 200이지만 **코스피 페이지를 반환**(title=코스피, now_value=6,197.54). 네이버가 심볼을 버리고 조용히 폴백 → 범위 가드가 6197을 걸러 항상 실패 |
| — | `api.finance.naver.com/siseJson.naver?symbol=KSVKOSPI` | 데이터 배열 **비어 있음**(헤더 행만) → history 37포인트뿐인 직접 원인 |
| 3 | investing.com `kospi-volatility` | 로컬에선 200(81.98)이나, as_of가 07‑27에 고착된 것으로 보아 **Actions 데이터센터 IP에서 차단** 추정 |
| 4 | yfinance `^VKOSPI` | **HTTP 404** |
| — | stooq `^vkospi.kr` | JS 챌린지 페이지 반환, CSV 없음 |

### 1.4 구조적 원인 — 왜 이 지경이 되도록 몰랐나

```
fetch_data.py      개별 소스 실패 → 직전 값 보존 (설계 의도상 올바름)
       ↓
validate_data.py   REQUIRED 6키 + KOSPI 시계열 길이 + USDKRW 존재만 차단
                   as-of 신선도·Source=="FAILED"·보존 누적은 WARN에 그침
       ↓
GitHub Actions     WARN은 로그 annotation → 아무도 안 봄
       ↓
index.html         전역 lastUpdated 하나만 표시. 지표별 as-of 표기 없음
                   (예외: sentiment 3종만 _sentCaption 이 3일 경과 경고)
       ↓
사용자             2021년 일본 CPI를 오늘 값으로 읽는다
```

**한 문장으로**: 신선도가 **데이터의 속성**이 아니라 **로그의 부산물**이라서, 어디서도 강제되지 않는다.

### 1.5 UI 통일성 결손 (실측)

| 항목 | 실측 |
|---|---|
| `new Chart(` 총 개수 | **48개** |
| 공통 옵션 팩토리 | **없음.** `Chart.defaults` 전역 몇 줄(`index.html:4272~4289`)뿐, 48개가 각자 인라인 options |
| `tension` | **6종** 혼재 — 0.3(49) / 0(5) / .2(3) / .25(2) / .15(2) / 0.2(1) |
| `borderWidth` | **5종** — 1(33) / 1.5(18) / 2(24) / 2.5(8) / 0(5) |
| `pointRadius` | 0(36) / 2(3) / 5 / 3 / 1.5 / 1 |
| 하드코딩 hex | **819개** 잔존 (astryx 전면 적용 후에도) + `rgba(` 70개 |
| off‑scale font-size | **69개** (11/12/13/10/12.5/9/11.5/17/22/18/10.5px …) |
| 지표별 as-of 표기 | **공통 컴포넌트 없음.** `_sentCaption`(`index.html:7451`)이 sentiment 3종만 처리, 나머지는 하드코딩 "출처:" 문자열 |

---

## 2. 설계 원칙

1. **신선도는 데이터에 실린다.** 모든 지표는 `asOf` + `sla` 를 갖고, 이를 계산하는 표는 **한 곳**에만 둔다.
2. **실패는 시끄럽게.** 조용한 보존을 금지하는 게 아니라, 보존된 사실이 **화면과 알림에 드러나게** 한다.
3. **게이트는 두 층.** 사이트를 못 쓰게 만드는 결손만 배포 차단(ERROR), 나머지는 표시(DEGRADED)하고 배포한다.
   — 죽은 지표 하나 때문에 전체 대시보드를 멈추는 건 더 나쁘다.
4. **차트는 규칙이지 취향이 아니다.** 48개 차트의 공통 옵션은 팩토리 1개에서 나오고, 개별 차트는 **다른 이유가 있을 때만** 덮어쓴다.
5. **소스는 이중화.** 1차가 죽으면 2차, 둘 다 죽으면 값을 조작하지 말고 `stale` 로 표기한다.

---

## 3. 해결 설계

### P1 — 데이터 신선도 계약 (`dataHealth`)

`scripts/data_sla.py` 신설. **지표 경로 → SLA** 단일 표:

```python
SLA = {
  # path,                          max_age_days, tier
  "indices.KOSPI":                 (1,  "critical"),
  "fx.USDKRW":                     (1,  "critical"),
  "sentiment.vkospi":              (4,  "important"),
  "stockMovers.kospiGainers":      (4,  "important"),
  "economicIndicators.us.cpi_us":  (45, "normal"),
  "economicIndicators.jp.cpi_jp":  (60, "normal"),
  # ...
}
```

`fetch_data.py`가 마지막에 이 표를 돌려 `data.json.dataHealth` 를 쓴다:

```json
"dataHealth": {
  "checkedAt": "2026-08-04T13:00:00+09:00",
  "summary": {"ok": 71, "stale": 8, "failed": 2},
  "items": [
    {"path":"sentiment.vkospi","asOf":"2026-07-27","ageDays":8,"sla":4,
     "state":"stale","tier":"important","source":"investing.com","note":"보존값"}
  ]
}
```

**같은 표를 3곳이 소비한다** — 이게 이 기획의 핵심이다.

| 소비자 | 동작 |
|---|---|
| `validate_data.py` | `tier=critical` 이 stale이면 **exit 1**(배포 차단). 나머지는 통과시키되 요약 출력 |
| `index.html` | 위젯마다 as-of 배지. stale이면 회색 처리 + 툴팁, failed면 ⚠ |
| `send_kakao_digest.py` | `failed` 발생 또는 `critical` stale 시 1일 1회 알림 (스팸 방지 상태 파일) |

### P2 — 소스 복구·교체

**실측 검증 완료된 교체표** (전부 `fredgraph.csv` / 공식 API 직접 호출로 최신값 확인):

| 지표 | 옛 소스 | 신규 소스 | 확인된 최신값 |
|---|---|---|---|
| 유로존 HICP | FRED OECD MEI | `FRED:CP0000EZ19M086NEST` | 2026‑06 = 103.00 |
| 독일 HICP | `FRED:DEUCPIALLMINMEI` | `FRED:CP0000DEM086NEST` | 2026‑06 = 102.32 |
| 영국 실질GDP | `FRED:CLVMNACSCAB1GQUK` | `FRED:NGDPRSAXDCGBQ` | 2026‑01 = 709,598 |
| **유로존 실업률** | `FRED:LRHUTTTTEZM156S` | **ECB Data Portal** `LFSI/M.I9.S.UNEHRT.TOTAL0.15_74.T` | 2026‑06 = 6.3% |
| **중국 CPI** | `FRED:CHNCPIALLMINMEI` | **OECD SDMX** `DSD_PRICES@DF_PRICES_ALL / CHN.M.N.CPI.PA._T.N.GY` | 2026‑06 = 1.0% |
| **영국 CPI** | `FRED:GBRCPIALLMINMEI` | **OECD SDMX** `GBR.M.N.CPI.PA._T.N.GY` | 2026‑06 = 2.8% |
| 일본 CPI | `FRED:JPNCPIALLMINMEI` | ⚠ **미확정** — OECD도 2021‑06에서 끊김(동일 상류). tradingeconomics 스크래핑(기존 PMI와 동일 경로) 또는 e‑Stat 무료 키 |
| 일본 광공업생산 | `FRED:JPNPROINDMISMEI` | ⚠ **미확정** — 동일 사유 |
| VKOSPI | 4단계 폴백 전멸 | KRX OpenAPI **파생상품지수 엔드포인트**로 교체 + VIX 교차검증 가드 |
| stockMovers | pykrx (로그인 실패) | **`KRX_ID`/`KRX_PW` 시크릿 등록** — 코드 수정 아님 |

ECB·OECD 모두 **인증 불필요·무료**. 공개 저장소 제약과 충돌하지 않는다.

**신규 지표 추가** (전부 생존 확인):

| 지표 | 시리즈 | 왜 |
|---|---|---|
| 미국 주간 신규실업수당 | `FRED:ICSA` (2026‑07‑25) | 현재 대시보드에 **주간 빈도 미국 지표가 없음** |
| 미국 장단기 금리차 10Y‑2Y | `FRED:T10Y2Y` (2026‑08‑03, 일간) | 침체 신호 대표 지표, 일간 갱신 |
| 미국 소비자심리 | `FRED:UMCSENT` | 소비 사이클 |
| 미국 비농업고용 수준 | `FRED:PAYEMS` | 캘린더에 NFP는 있으나 시계열 없음 |
| 달러 인덱스(광의) | `FRED:DTWEXBGS` (일간) | 기존 `broad_dollar` 보강 |

### P3 — VKOSPI 교차검증 가드

범위 가드 `5<v<100` 은 유가·다른 지수를 통과시킨다. **VIX 대비 비율 가드**를 추가한다:

```python
def _is_valid_vkospi(v, vix=None):
    if v is None or not (5 < v < 100): return False
    if vix and not (0.5 <= v / vix <= 3.0):   # 한·미 변동성은 이 배수를 벗어나지 않는다
        return False
    return True
```

현재 78.3 / VIX 15.99 = **4.9배** → 이 가드에 걸린다. 통과 소스가 하나도 없으면 값을 쓰지 말고 `state:"failed"` 로 남긴다 — **틀린 값보다 빈 값이 낫다.**

### P4 — 차트 UI 통일

**기존 48개 차트를 전부 손대지 않는다.** 3단계로 최소 diff:

1. **`chartBase()` 팩토리 + `Chart.defaults` 확장** — tension 0.3 / borderWidth 1.5 / pointRadius 0 / grid·tick 토큰 / 애니메이션 duration을 한 곳에서 정의.
2. **중복 리터럴 제거** — 새 기본값과 **동일한** 값만 스크립트로 삭제(`tension:0.3` 49곳, `pointRadius:0` 36곳). 렌더 결과 무변화, 순수 잡음 제거.
3. **이상치 정규화** — `.2/.15/.25 → 0.3`, `borderWidth 2.5 → 2`, `1 → 1.5`. 여기서만 실제 시각 변화 발생.

**as-of 배지 공통화** — `_sentCaption`(sentiment 3종 전용)을 `asOfBadge(path)` 로 일반화해 `dataHealth.items` 를 읽게 하고, 하드코딩 "출처:" 문자열을 이 컴포넌트로 흡수.

**토큰 위반 정리** — hex 819개·off-scale font 69개 중 **차트 관련부터** 우선 토큰화 (`window._UPDN` 등 CLAUDE.md 명시 예외는 유지).

### P5 — 실패 가시화

| 층 | 지금 | 개선 |
|---|---|---|
| CI | WARN이 로그 annotation | `dataHealth.summary` 를 **Job Summary**에 표로 출력 |
| 사이트 | 전역 lastUpdated 1개 | 헤더에 **데이터 상태 칩**(정상 71 / 지연 8 / 실패 2), 클릭 시 시스템 진단 패널 |
| 알림 | 없음 | `failed` 또는 `critical` stale 발생 시 카톡 1일 1회 (`alerts_state.json` 방식 재사용) |

---

## 4. 실행 계획

| 단계 | 내용 | 산출물 | 위험 |
|---|---|---|---|
| **1** | `data_sla.py` + `dataHealth` 생성 + `validate_data.py` 2층 게이트 | 신규 파일 1, 수정 2 | 낮음 (읽기 위주) |
| **2** | 죽은 소스 6종 교체 (ECB·OECD·FRED 신규 ID) | `fetch_data.py` 부분 수정 | 중 — 파서 신규 |
| **3** | VKOSPI 교차검증 가드 + KRX 파생지수 엔드포인트 | `fetch_data.py` | 중 |
| **4** | 신규 지표 5종 (ICSA·T10Y2Y·UMCSENT·PAYEMS·DTWEXBGS) | `fetch_data.py` + 위젯 | 낮음 |
| **5** | 차트 팩토리 + 리터럴 정규화 + as-of 배지 | `index.html` | 중 — 48차트 회귀 확인 필요 |
| **6** | 데이터 상태 칩 + Job Summary + 카톡 알림 | 3파일 | 낮음 |

**검증**: 각 단계마다 `python scripts/validate_data.py` + 실제 사이트 브라우저 렌더 확인(콘솔 에러 0).

---

## 5. 사용자 조치가 필요한 항목 (코드로 해결 불가)

| # | 항목 | 조치 |
|---|---|---|
| **A1** | `stockMovers` 상시 FAILED | data.krx.co.kr 무료 회원가입 후 **`KRX_ID` / `KRX_PW`** 를 GitHub Secrets에 등록. 이것 하나로 종목·투자자별 매매동향이 함께 복구된다 |
| **A2** | 일본 CPI·광공업생산 | e‑Stat 무료 appId 발급(권장) 또는 tradingeconomics 스크래핑 허용 여부 결정 |
| **A3** | `realestate.kr` 단위 검증 | `unsold_kr` 296,502 / `start_kr` 102.17 의 R‑ONE 원 단위 확인 필요 (지표 코드 A_2024_00064 / A_2024_00057) |
